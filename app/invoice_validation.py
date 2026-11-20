"""Validación de salida: la factura se revisa antes de llegar a la persona.

Es independiente de ``app.invoice``: no reutiliza sus funciones de cálculo, para
que un error en el servicio no se valide a sí mismo. Revisa el esquema, que el
cliente y cada concepto existan en el catálogo con los mismos datos, y que los
importes, el subtotal, el IVA y el total se recalculen igual.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from app.catalog import Catalog

INVOICE_KEYS = frozenset(
    {
        "folio",
        "fecha",
        "estado",
        "moneda",
        "cliente",
        "lineas",
        "subtotal",
        "iva",
        "total",
    }
)
CLIENT_KEYS = frozenset({"id", "nombre", "rfc"})
LINE_KEYS = frozenset(
    {"concepto_id", "descripcion", "unidad", "cantidad", "precio_unitario", "importe"}
)
MONEY_TEXT = re.compile(r"\d+\.\d{2}")
DATE_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}")
EXPECTED_STATUS = "borrador"
EXPECTED_CURRENCY = "MXN"
VAT_PERCENT = Decimal("16")
HUNDRED = Decimal("100")
TWO_PLACES = Decimal("0.01")


class InvoiceValidationError(Exception):
    """La factura no cumple el esquema o sus cuentas no cuadran.

    El mensaje lista los campos que fallan, sin sus valores.
    """


def _money_value(text: object) -> Decimal:
    """Convierte un texto con 2 decimales en ``Decimal``.

    :param text: Valor de la factura.
    :type text: object
    :return: El número.
    :rtype: Decimal
    :raises ValueError: Si no es texto con el formato ``0.00``.
    """
    if not isinstance(text, str) or not MONEY_TEXT.fullmatch(text):
        raise ValueError("money must be text with 2 decimals")
    return Decimal(text)


def _client_problems(invoice: dict, catalog: Catalog) -> List[str]:
    """Revisa que el cliente exista y coincida con el catálogo.

    :param invoice: Factura a revisar.
    :type invoice: dict
    :param catalog: Catálogo cerrado.
    :type catalog: Catalog
    :return: Campos con problema.
    :rtype: list[str]
    """
    client = invoice.get("cliente")
    if not isinstance(client, dict) or set(client) != CLIENT_KEYS:
        return ["cliente"]
    known = catalog.client_by_id(str(client["id"]))
    if known is None:
        return ["cliente.id"]
    if (client["nombre"], client["rfc"]) != (known.nombre, known.rfc):
        return ["cliente"]
    return []


def _line_problems(  # pylint: disable=too-many-return-statements
    index: int, line: object, catalog: Catalog, max_quantity: int
) -> List[str]:
    """Revisa una línea contra el catálogo y recalcula su importe.

    :param index: Posición de la línea, para el mensaje.
    :type index: int
    :param line: Línea de la factura.
    :type line: object
    :param catalog: Catálogo cerrado.
    :type catalog: Catalog
    :param max_quantity: Cantidad máxima por línea.
    :type max_quantity: int
    :return: Campos con problema.
    :rtype: list[str]
    """
    name = f"lineas[{index}]"
    if not isinstance(line, dict) or set(line) != LINE_KEYS:
        return [name]
    concept = catalog.concept_by_id(str(line["concepto_id"]))
    if concept is None:
        return [name + ".concepto_id"]
    if (line["descripcion"], line["unidad"]) != (concept.descripcion, concept.unidad):
        return [name + ".descripcion"]
    quantity = line["cantidad"]
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        return [name + ".cantidad"]
    if not 1 <= quantity <= max_quantity:
        return [name + ".cantidad"]
    try:
        price = _money_value(line["precio_unitario"])
        amount = _money_value(line["importe"])
    except ValueError:
        return [name]
    if price != concept.precio_unitario:
        return [name + ".precio_unitario"]
    if amount != price * quantity:
        return [name + ".importe"]
    return []


def _totals_problems(invoice: dict, lines_sum: Decimal) -> List[str]:
    """Recalcula subtotal, IVA y total.

    :param invoice: Factura a revisar.
    :type invoice: dict
    :param lines_sum: Suma de los importes ya revisados.
    :type lines_sum: Decimal
    :return: Campos con problema.
    :rtype: list[str]
    """
    try:
        subtotal = _money_value(invoice["subtotal"])
        vat = _money_value(invoice["iva"])
        total = _money_value(invoice["total"])
    except ValueError:
        return ["subtotal, iva o total"]
    found = []
    if subtotal != lines_sum:
        found.append("subtotal")
    expected_vat = (lines_sum * VAT_PERCENT / HUNDRED).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    if vat != expected_vat:
        found.append("iva")
    if total != lines_sum + expected_vat:
        found.append("total")
    return found


def _header_problems(invoice: dict) -> List[str]:
    """Revisa folio, fecha, estado y moneda.

    :param invoice: Factura a revisar.
    :type invoice: dict
    :return: Campos con problema.
    :rtype: list[str]
    """
    found = []
    if not isinstance(invoice["folio"], str) or not invoice["folio"].strip():
        found.append("folio")
    if not isinstance(invoice["fecha"], str) or not DATE_TEXT.match(invoice["fecha"]):
        found.append("fecha")
    if invoice["estado"] != EXPECTED_STATUS:
        found.append("estado")
    if invoice["moneda"] != EXPECTED_CURRENCY:
        found.append("moneda")
    return found


def validate_invoice(
    invoice: object, catalog: Catalog, max_lines: int, max_quantity: int
) -> None:
    """Comprueba la factura completa; no devuelve nada si todo cuadra.

    :param invoice: Factura que devolvió el servicio.
    :type invoice: object
    :param catalog: Catálogo cerrado.
    :type catalog: Catalog
    :param max_lines: Máximo de líneas por factura.
    :type max_lines: int
    :param max_quantity: Cantidad máxima por línea.
    :type max_quantity: int
    :raises InvoiceValidationError: Si algo no cumple; el mensaje nombra los
        campos, nunca sus valores.
    """
    if not isinstance(invoice, dict) or set(invoice) != INVOICE_KEYS:
        raise InvoiceValidationError("invoice does not match the schema")
    found = _header_problems(invoice) + _client_problems(invoice, catalog)
    lines = invoice["lineas"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= max_lines:
        raise InvoiceValidationError("lineas does not match the schema")
    for index, line in enumerate(lines):
        found.extend(_line_problems(index, line, catalog, max_quantity))
    if not found:
        lines_sum = sum((Decimal(line["importe"]) for line in lines), Decimal("0"))
        found.extend(_totals_problems(invoice, lines_sum))
    if found:
        raise InvoiceValidationError("invalid fields: " + ", ".join(found))
