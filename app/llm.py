"""Interfaz del modelo de lenguaje, modelo simulado y fábrica de modelos."""

import json
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import httpx

from app.catalog import Catalog, Mention, find_mentions, normalize
from app.completion import Completion, LanguageModel
from app.config import PROVIDER_FAKE, PROVIDER_GATEWAY, Settings
from app.directory import EmployeeDirectory
from app.gateway import GatewayModel

__all__ = [
    "Completion",
    "FakeModel",
    "LanguageModel",
    "build_models",
    "HELP_MESSAGE",
    "INVOICE_MARKER",
    "TOOL_RESULT_PREFIX",
]

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
HELP_MESSAGE = "Pregúntame por un empleado (EMP-0001) o un departamento."
EMPLOYEE_ID_PATTERN = re.compile(r"EMP-\d{4}")
DEFAULT_FAKE_NAME = "fake"

INVOICE_MARKER = "[factura]"
INVOICE_TOOL = "crear_factura"
SEGMENT_SEPARATORS = (",", " y ")
QUANTITY_TOKEN = re.compile(r"(?<!\w)(\d+|un|una)(?!\w)")
DEFAULT_QUANTITY = 1
INVOICE_FAILED_PREFIX = "No pude crear la factura: "


def _is_invoice_conversation(messages: Sequence[Mapping[str, str]]) -> bool:
    """Indica si la conversación es del agente de facturación.

    :param messages: Mensajes con ``role`` y ``content``.
    :type messages: Sequence[Mapping[str, str]]
    :return: ``True`` si empieza con un mensaje de sistema ``[factura]``.
    :rtype: bool
    """
    if not messages:
        return False
    first = messages[0]
    return first["role"] == "system" and str(first["content"]).startswith(
        INVOICE_MARKER
    )


def _quantity_before(folded: str, mention: Mention) -> int:
    """Cantidad de un concepto: el entero más cercano a su izquierda.

    Solo se busca dentro del mismo tramo (los tramos se separan con ``,`` y
    `` y ``). Sin número, o con ``un``/``una``, la cantidad es 1.

    :param folded: Frase normalizada.
    :type folded: str
    :param mention: Mención del concepto dentro de ``folded``.
    :type mention: Mention
    :return: La cantidad.
    :rtype: int
    """
    start = 0
    for separator in SEGMENT_SEPARATORS:
        position = folded.rfind(separator, 0, mention.start)
        if position >= 0:
            start = max(start, position + len(separator))
    tokens = QUANTITY_TOKEN.findall(folded[start:mention.start])
    if not tokens or not tokens[-1].isdigit():
        return DEFAULT_QUANTITY
    return int(tokens[-1])


def _invoice_summary(result: str) -> str:
    """Respuesta final del simulado a partir del resultado de ``crear_factura``.

    :param result: Texto que devolvió la herramienta.
    :type result: str
    :return: ``Factura <folio> creada para <cliente>: total <total> MXN`` o
        el aviso de que no se pudo.
    :rtype: str
    """
    try:
        invoice = json.loads(result)
        return (
            f"Factura {invoice['folio']} creada para "
            f"{invoice['cliente']['nombre']}: total {invoice['total']} MXN"
        )
    except (ValueError, TypeError, KeyError):
        return INVOICE_FAILED_PREFIX + result


def _count_words(texts: Iterable[str]) -> int:
    """Cuenta palabras separadas por espacios.

    :param texts: Textos a contar.
    :type texts: Iterable[str]
    :return: Total de palabras.
    :rtype: int
    """
    return sum(len(str(text).split()) for text in texts)


class FakeModel:  # pylint: disable=too-few-public-methods
    """Modelo simulado, determinista y sin red.

    El nombre solo sirve para calcular el costo con el precio de ese modelo:
    dos simulados con distinto nombre responden exactamente igual.

    :param departments: Departamentos que existen en los datos.
    :type departments: Iterable[str]
    :param name: Nombre con el que se cobra, por ejemplo ``MODEL_SMALL``.
    :type name: str
    :param catalog: Catálogo para el modo ``[factura]``; sin él, ese modo
        responde que no hay catálogo.
    :type catalog: Catalog or None
    """

    def __init__(
        self,
        departments: Iterable[str],
        name: str = DEFAULT_FAKE_NAME,
        catalog: Optional[Catalog] = None,
    ) -> None:
        self._departments = tuple(departments)
        self.name = name
        self._catalog = catalog

    def complete(self, messages: Sequence[Mapping[str, str]]) -> Completion:
        """Decide la respuesta con las reglas del spec sobre el último mensaje.

        Si la conversación empieza con el sistema ``[factura]`` aplica las
        reglas del agente de facturación; si no, las del asistente de RH.

        :param messages: Mensajes con ``role`` y ``content``.
        :type messages: Sequence[Mapping[str, str]]
        :return: Un objeto JSON con ``tool``/``args`` o con ``answer``.
        :rtype: Completion
        """
        last = str(messages[-1]["content"]) if messages else ""
        if _is_invoice_conversation(messages):
            reply = self._decide_invoice(last)
        else:
            reply = self._decide(last)
        text = json.dumps(reply, ensure_ascii=False)
        return Completion(
            text=text,
            input_tokens=_count_words(m["content"] for m in messages),
            output_tokens=_count_words([text]),
        )

    def _decide(self, last: str) -> dict:
        """Aplica las cuatro reglas en orden de prioridad.

        :param last: Contenido del último mensaje.
        :type last: str
        :return: Respuesta del protocolo.
        :rtype: dict
        """
        if last.startswith(TOOL_RESULT_PREFIX):
            result = last[len(TOOL_RESULT_PREFIX):]
            return {"answer": "Según el directorio: " + result}
        match = EMPLOYEE_ID_PATTERN.search(last)
        if match:
            return {"tool": "get_employee", "args": {"employee_id": match.group(0)}}
        department = self._find_department(last)
        if department is not None:
            return {
                "tool": "search_by_department",
                "args": {"department": department},
            }
        return {"answer": HELP_MESSAGE}

    def _decide_invoice(self, last: str) -> dict:
        """Reglas del modo ``[factura]``: pide ``crear_factura`` o resume.

        :param last: Contenido del último mensaje.
        :type last: str
        :return: Respuesta del protocolo.
        :rtype: dict
        """
        if last.startswith(TOOL_RESULT_PREFIX):
            return {"answer": _invoice_summary(last[len(TOOL_RESULT_PREFIX):])}
        if self._catalog is None:
            return {"answer": INVOICE_FAILED_PREFIX + "no hay catálogo."}
        clients = find_mentions(last, self._catalog.clients)
        folded = normalize(last)
        concepts = [
            {"concepto": mention.alias, "cantidad": _quantity_before(folded, mention)}
            for mention in find_mentions(last, self._catalog.concepts)
        ]
        return {
            "tool": INVOICE_TOOL,
            "args": {
                "cliente": clients[0].alias if clients else "",
                "conceptos": concepts,
            },
        }

    def _find_department(self, text: str) -> Optional[str]:
        """Busca un departamento mencionado en el texto, sin distinguir mayúsculas.

        :param text: Texto a revisar.
        :type text: str
        :return: Nombre del departamento o ``None``.
        :rtype: str or None
        """
        folded = text.casefold()
        for department in self._departments:
            if department.casefold() in folded:
                return department
        return None


def build_models(
    settings: Settings,
    directory: EmployeeDirectory,
    client: Optional[httpx.Client] = None,
    catalog: Optional[Catalog] = None,
) -> Dict[str, LanguageModel]:
    """Crea los dos modelos (``MODEL_SMALL`` y ``MODEL_LARGE``) del proveedor.

    :param settings: Configuración validada.
    :type settings: Settings
    :param directory: Directorio de empleados (para conocer los departamentos).
    :type directory: EmployeeDirectory
    :param client: Cliente HTTP del gateway; ``None`` crea uno con timeout.
    :type client: httpx.Client or None
    :param catalog: Catálogo de facturación para el simulado; ``None`` lo lee
        de ``CLIENTES_PATH`` y ``CONCEPTOS_PATH``.
    :type catalog: Catalog or None
    :return: Un modelo por nombre.
    :rtype: dict[str, LanguageModel]
    :raises ValueError: Si el proveedor no está soportado.
    """
    names = (settings.model_small, settings.model_large)
    if settings.model_provider == PROVIDER_FAKE:
        departments: List[str] = directory.departments()
        known = catalog or Catalog.from_files(
            settings.clientes_path, settings.conceptos_path
        )
        return {
            name: FakeModel(departments, name=name, catalog=known) for name in names
        }
    if settings.model_provider == PROVIDER_GATEWAY:
        shared = client or httpx.Client()
        return {
            name: GatewayModel(settings=settings, model=name, client=shared)
            for name in names
        }
    raise ValueError(f"MODEL_PROVIDER not supported: {settings.model_provider!r}")
