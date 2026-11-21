"""``POST /invoice``: borrador de factura a partir de una frase.

El modelo solo interpreta la frase; la respuesta sale de la factura que armó y
validó el código, nunca del texto del modelo. No se timbra ni se guarda nada.
Los eventos ``audit`` llevan el cliente de la clave y nunca textos ni valores
de PII: solo folio, id del cliente, total, motivo o tipos.
"""

from dataclasses import dataclass
from typing import Callable, List, Mapping, Sequence

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.agent import Agent, AgentResult
from app.catalog import Catalog
from app.completion import LanguageModel
from app.config import Settings
from app.invoice_agent import (
    INVOICE_SYSTEM_PROMPT,
    InvoiceCreator,
    InvoiceOutcome,
    InvoiceTool,
)
from app.invoice_validation import InvoiceValidationError, validate_invoice
from app.logging_json import JsonLogger
from app.metrics import Metrics
from app.pii import REPORT_ORDER, detect, mask
from app.pricing import PriceTable
from app.router import choose_route
from app.tracing import request_context

BUSINESS_ERROR_STATUS = 422
VALIDATION_FAILED_STATUS = 500
VALIDATION_FAILED_DETAIL = "invoice failed validation"
NOT_INTERPRETED = "no se pudo interpretar la factura"
INVOICE_RUN_NAME = "invoice_agent.run"

Tracer = Callable[[str, str], Callable]


class InvoiceClient(BaseModel):
    """Cliente de la factura (el RFC completo, para la persona autenticada)."""

    id: str
    nombre: str
    rfc: str


class InvoiceLine(BaseModel):
    """Línea de la factura; el dinero va como texto con 2 decimales."""

    concepto_id: str
    descripcion: str
    unidad: str
    cantidad: int
    precio_unitario: str
    importe: str


class Invoice(BaseModel):
    """Borrador de factura sin validez fiscal, en MXN."""

    folio: str
    fecha: str
    estado: str
    moneda: str
    cliente: InvoiceClient
    lineas: List[InvoiceLine]
    subtotal: str
    iva: str
    total: str


class InvoiceResponse(BaseModel):
    """Respuesta ``200`` de ``POST /invoice``.

    ``pii_detected`` lleva solo tipos (``rfc``, ``curp``, ``email``,
    ``phone``), nunca valores.
    """

    invoice: Invoice
    steps: int
    tools_used: List[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    request_id: str
    pii_detected: List[str]


def build_invoice_request_model(max_chars: int) -> type:
    """Crea el modelo del cuerpo de ``POST /invoice`` con el largo máximo.

    :param max_chars: Largo máximo de la frase (``MAX_QUESTION_CHARS``).
    :type max_chars: int
    :return: Clase Pydantic con el campo ``text``.
    :rtype: type
    """

    class InvoiceRequest(BaseModel):
        """Cuerpo de ``POST /invoice``."""

        text: str = Field(min_length=1, max_length=max_chars)

        @field_validator("text")
        @classmethod
        def _text_not_blank(cls, value: str) -> str:
            """Rechaza frases formadas solo por espacios."""
            if not value.strip():
                raise ValueError("text must not be blank")
            return value

    return InvoiceRequest


@dataclass(frozen=True)
class InvoiceDependencies:  # pylint: disable=too-many-instance-attributes
    """Lo que necesita ``POST /invoice``, inyectado desde ``create_app``.

    :param settings: Configuración validada.
    :type settings: Settings
    :param models: Modelos por nombre.
    :type models: Mapping[str, LanguageModel]
    :param catalog: Catálogo cerrado.
    :type catalog: Catalog
    :param service: Servicio que arma la factura.
    :type service: InvoiceCreator
    :param logger: Logger JSON.
    :type logger: JsonLogger
    :param metrics: Métricas del proceso.
    :type metrics: Metrics
    :param prices: Tabla de precios.
    :type prices: PriceTable
    :param tracer: Fábrica de decoradores de traza.
    :type tracer: Callable
    """

    settings: Settings
    models: Mapping[str, LanguageModel]
    catalog: Catalog
    service: InvoiceCreator
    logger: JsonLogger
    metrics: Metrics
    prices: PriceTable
    tracer: Tracer


@dataclass(frozen=True)
class _Request:
    """Datos de la petición en curso.

    :param request_id: Id de la petición.
    :type request_id: str
    :param client: Cliente de la clave (nunca la clave).
    :type client: str
    """

    request_id: str
    client: str


def _merge_types(*groups: Sequence[str]) -> List[str]:
    """Une listas de tipos de PII en el orden fijo y sin repetidos.

    :param groups: Listas de tipos.
    :type groups: Sequence[str]
    :return: Tipos unidos.
    :rtype: list[str]
    """
    found = {kind for group in groups for kind in group}
    return [kind for kind in REPORT_ORDER if kind in found]


class InvoiceHandler:
    """Atiende ``POST /invoice`` de principio a fin.

    :param deps: Dependencias inyectadas.
    :type deps: InvoiceDependencies
    """

    def __init__(self, deps: InvoiceDependencies) -> None:
        self._deps = deps

    def handle(self, text: str, request_id: str, client: str) -> object:
        """Convierte la frase en un borrador de factura.

        :param text: Frase de la persona.
        :type text: str
        :param request_id: Id de la petición.
        :type request_id: str
        :param client: Cliente autenticado.
        :type client: str
        :return: ``InvoiceResponse`` o un ``JSONResponse`` de error (``422``
            de negocio o ``500`` si la factura no pasa la validación).
        :rtype: InvoiceResponse or JSONResponse
        :raises ModelUnavailableError: Si el modelo real no responde.
        """
        settings = self._deps.settings
        current = _Request(request_id=request_id, client=client)
        input_types = detect(text)
        if input_types:
            self._audit(current, "pii_detected", types=input_types)
        phrase = mask(text) if settings.pii_masking else text
        tool = InvoiceTool(
            self._deps.service, self._deps.catalog, phrase, settings.pii_masking
        )
        result = self._run_agent(phrase, tool, current)
        self._deps.metrics.record_tokens(result.input_tokens, result.output_tokens)
        self._deps.metrics.record_cost(result.cost_usd)
        answer_types = self._answer_types(result.answer, tool.outcome)
        new_types = [kind for kind in answer_types if kind not in input_types]
        if new_types:
            self._audit(current, "pii_detected", types=new_types)
        pii_types = _merge_types(input_types, answer_types)
        if pii_types:
            self._deps.metrics.record_pii_detected()
        return self._respond(tool.outcome, result, current, pii_types)

    def _run_agent(
        self, phrase: str, tool: InvoiceTool, current: _Request
    ) -> AgentResult:
        """Corre el agente de facturación con su única herramienta.

        :param phrase: Frase ya enmascarada si aplica.
        :type phrase: str
        :param tool: Herramienta ``crear_factura`` de esta petición.
        :type tool: InvoiceTool
        :param current: Petición en curso.
        :type current: _Request
        :return: Resultado del bucle.
        :rtype: AgentResult
        """
        settings = self._deps.settings
        route = choose_route(phrase, settings)
        agent = Agent(
            model=self._deps.models[route.model],
            directory=None,
            max_steps=settings.agent_max_steps,
            logger=self._deps.logger,
            tracer=self._deps.tracer,
            prices=self._deps.prices,
            history_window=0,
            tools=[tool.tool()],
            system_prompt=INVOICE_SYSTEM_PROMPT,
            run_name=INVOICE_RUN_NAME,
        )
        with request_context(settings, current.request_id, client=current.client):
            return agent.run(
                phrase,
                [],
                request_id=current.request_id,
                route=route,
                client=current.client,
            )

    @staticmethod
    def _answer_types(answer: str, outcome: InvoiceOutcome) -> List[str]:
        """Tipos de PII en la respuesta del modelo, sin contar el folio.

        :param answer: Respuesta final del modelo.
        :type answer: str
        :param outcome: Lo que pasó con la herramienta.
        :type outcome: InvoiceOutcome
        :return: Tipos encontrados.
        :rtype: list[str]
        """
        folio = (outcome.invoice or {}).get("folio")
        if isinstance(folio, str) and folio:
            answer = answer.replace(folio, "")
        return detect(answer)

    def _respond(
        self,
        outcome: InvoiceOutcome,
        result: AgentResult,
        current: _Request,
        pii_types: List[str],
    ) -> object:
        """Decide la respuesta con lo que guardó la herramienta.

        :param outcome: Lo que pasó con la herramienta.
        :type outcome: InvoiceOutcome
        :param result: Resultado del bucle.
        :type result: AgentResult
        :param current: Petición en curso.
        :type current: _Request
        :param pii_types: Tipos de PII detectados.
        :type pii_types: list[str]
        :return: La respuesta HTTP.
        :rtype: InvoiceResponse or JSONResponse
        """
        if outcome.invoice is None:
            reason = outcome.rejection or NOT_INTERPRETED
            return self._reject(current, reason, BUSINESS_ERROR_STATUS)
        settings = self._deps.settings
        try:
            validate_invoice(
                outcome.invoice,
                self._deps.catalog,
                settings.max_invoice_lines,
                settings.max_line_quantity,
            )
            invoice = Invoice.model_validate(outcome.invoice)
        except (InvoiceValidationError, ValueError):
            return self._reject(
                current, VALIDATION_FAILED_DETAIL, VALIDATION_FAILED_STATUS
            )
        self._audit(
            current,
            "invoice_created",
            folio=invoice.folio,
            client_id=invoice.cliente.id,
            total=invoice.total,
        )
        self._deps.metrics.record_invoice_created()
        return InvoiceResponse(
            invoice=invoice,
            steps=result.steps,
            tools_used=list(result.tools_used),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            request_id=current.request_id,
            pii_detected=pii_types,
        )

    def _reject(self, current: _Request, reason: str, status: int) -> JSONResponse:
        """Registra el rechazo y arma la respuesta de error.

        :param current: Petición en curso.
        :type current: _Request
        :param reason: Motivo (mensaje fijo, sin datos de la frase).
        :type reason: str
        :param status: Código HTTP.
        :type status: int
        :return: ``{"detail": reason}`` con el código indicado.
        :rtype: JSONResponse
        """
        self._audit(current, "invoice_rejected", reason=reason)
        self._deps.metrics.record_invoice_rejected()
        return JSONResponse({"detail": reason}, status_code=status)

    def _audit(self, current: _Request, action: str, **fields: object) -> None:
        """Escribe un evento ``audit`` con el cliente y el id de la petición.

        :param current: Petición en curso.
        :type current: _Request
        :param action: ``invoice_created``, ``invoice_rejected`` o
            ``pii_detected``.
        :type action: str
        :param fields: Campos propios del evento (nunca textos ni valores).
        :type fields: object
        """
        self._deps.logger.emit(
            "audit",
            current.request_id,
            client=current.client,
            action=action,
            **fields,
        )
