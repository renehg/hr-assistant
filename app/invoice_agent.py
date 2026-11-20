"""Herramienta ``crear_factura`` del agente de facturación (mínimo privilegio).

El agente de facturación solo conoce esta herramienta. Cada petición crea su
propia ``InvoiceTool``: la factura completa (con el RFC entero) se guarda aquí,
fuera de las funciones trazadas, y al modelo solo le llega una copia con el RFC
enmascarado.
"""

import copy
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from app.agent import Tool
from app.catalog import Catalog, find_mentions
from app.invoice import CLIENT_NOT_FOUND, InvoiceRejected
from app.llm import INVOICE_MARKER
from app.pii import mask_rfc

INVOICE_TOOL_NAME = "crear_factura"
INVOICE_SYSTEM_PROMPT = (
    INVOICE_MARKER + " Eres el asistente de facturación. Responde siempre con un "
    "único objeto JSON y nada más. Para crear el borrador pide la herramienta "
    '{"tool": "crear_factura", "args": {"cliente": "nombre del cliente como '
    'aparece en la frase", "conceptos": [{"concepto": "texto del concepto", '
    '"cantidad": 1}]}}. La cantidad es un entero. No mandes precios, ids, '
    "impuestos ni totales: el sistema los calcula. Cuando recibas el resultado "
    'escribe {"answer": "resumen breve en español"}.'
)
MISSING_ARGUMENTS = (
    'error: crear_factura necesita "cliente" (texto) y "conceptos" (lista).'
)
ALREADY_USED = "error: crear_factura ya se usó en esta petición."
TOOL_ERROR_PREFIX = "error: "


class InvoiceCreator(Protocol):  # pylint: disable=too-few-public-methods
    """Interfaz del servicio que arma la factura (se puede inyectar)."""

    def create(self, cliente: object, conceptos: object) -> dict:
        """Arma la factura o lanza ``InvoiceRejected``.

        :param cliente: Texto con el que se menciona al cliente.
        :type cliente: object
        :param conceptos: Lista de ``{"concepto", "cantidad"}``.
        :type conceptos: object
        :return: La factura.
        :rtype: dict
        """


@dataclass
class InvoiceOutcome:
    """Lo que pasó con ``crear_factura`` en una petición.

    :param called: Si el modelo llegó a usar la herramienta.
    :type called: bool
    :param invoice: Factura armada por el servicio, o ``None``.
    :type invoice: dict or None
    :param rejection: Motivo de negocio si se rechazó, o ``None``.
    :type rejection: str or None
    """

    called: bool = False
    invoice: Optional[dict] = None
    rejection: Optional[str] = None


def _parse_arguments(args: object) -> Optional[Dict[str, Any]]:
    """Acepta solo ``cliente`` (texto) y ``conceptos`` (lista); ignora el resto.

    Lo que el modelo mande de más (precios, ids, totales) se descarta aquí.

    :param args: Argumentos pedidos por el modelo.
    :type args: object
    :return: Los dos argumentos o ``None`` si no sirven.
    :rtype: dict or None
    """
    if not isinstance(args, dict):
        return None
    cliente, conceptos = args.get("cliente"), args.get("conceptos")
    if not isinstance(cliente, str) or not isinstance(conceptos, list):
        return None
    return {"cliente": cliente, "conceptos": conceptos}


def _audit_arguments(args: Dict[str, Any]) -> Dict[str, Any]:
    """Lo que va a la auditoría: solo cuántos conceptos se pidieron.

    :param args: Argumentos ya validados.
    :type args: dict
    :return: ``{"conceptos": <número>}``; nunca el texto del modelo.
    :rtype: dict
    """
    return {"conceptos": len(args["conceptos"])}


class InvoiceTool:
    """Herramienta ``crear_factura`` de una sola petición.

    :param service: Servicio que arma la factura.
    :type service: InvoiceCreator
    :param catalog: Catálogo cerrado.
    :type catalog: Catalog
    :param phrase: Frase que recibió el modelo (ya enmascarada si aplica); el
        cliente que pida el modelo debe aparecer en ella.
    :type phrase: str
    :param mask_for_model: Si el RFC del cliente se enmascara para el modelo.
    :type mask_for_model: bool
    """

    def __init__(
        self,
        service: InvoiceCreator,
        catalog: Catalog,
        phrase: str,
        mask_for_model: bool,
    ) -> None:
        self._service = service
        self._catalog = catalog
        self._phrase = phrase
        self._mask_for_model = mask_for_model
        self.outcome = InvoiceOutcome()

    def tool(self) -> Tool:
        """Describe la herramienta para el agente.

        :return: La herramienta ``crear_factura``.
        :rtype: Tool
        """
        return Tool(
            name=INVOICE_TOOL_NAME,
            parse_args=_parse_arguments,
            run=self.crear_factura,
            audit_args=_audit_arguments,
            missing_message=MISSING_ARGUMENTS,
        )

    def crear_factura(self, cliente: str, conceptos: list) -> str:
        """Arma la factura una sola vez por petición.

        :param cliente: Texto con el que la frase menciona al cliente.
        :type cliente: str
        :param conceptos: Lista de ``{"concepto", "cantidad"}``.
        :type conceptos: list
        :return: La factura para el modelo (RFC enmascarado) o un error.
        :rtype: str
        """
        if self.outcome.called:
            return ALREADY_USED
        self.outcome.called = True
        try:
            self._check_client_in_phrase(cliente)
            invoice = self._service.create(cliente, conceptos)
        except InvoiceRejected as rejected:
            self.outcome.rejection = rejected.reason
            return TOOL_ERROR_PREFIX + rejected.reason
        self.outcome.invoice = invoice
        return json.dumps(self._for_model(invoice), ensure_ascii=False, default=str)

    def _check_client_in_phrase(self, cliente: str) -> None:
        """Exige que el cliente pedido por el modelo aparezca en la frase.

        Así el modelo no puede cambiar de cliente ni facturar a otro.

        :param cliente: Texto del cliente que mandó el modelo.
        :type cliente: str
        :raises InvoiceRejected: Si el cliente existe pero no está en la frase.
        """
        requested = self._catalog.find_client(cliente)
        if requested is None:
            return
        mentioned = {
            mention.entry.id
            for mention in find_mentions(self._phrase, self._catalog.clients)
        }
        if requested.id not in mentioned:
            raise InvoiceRejected(CLIENT_NOT_FOUND)

    def _for_model(self, invoice: object) -> object:
        """Copia de la factura para el modelo, con el RFC del cliente parcial.

        :param invoice: Factura armada por el servicio.
        :type invoice: object
        :return: La copia que verá el modelo.
        :rtype: object
        """
        shown = copy.deepcopy(invoice)
        client = shown.get("cliente") if isinstance(shown, dict) else None
        if self._mask_for_model and isinstance(client, dict):
            rfc = client.get("rfc")
            client["rfc"] = mask_rfc(rfc) if isinstance(rfc, str) else ""
        return shown
