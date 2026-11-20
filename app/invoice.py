"""Reglas de negocio del borrador de factura: el código calcula, no el modelo.

El modelo solo manda el texto del cliente y pares ``{concepto, cantidad}``.
Aquí se resuelven contra el catálogo, se revisan los rangos y se calcula todo
con ``Decimal``. No se timbra ni se guarda nada.
"""

import uuid
from datetime import timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, List, Optional, Sequence, Tuple

from app.catalog import Catalog, Client, Concept
from app.clock import Clock

CLIENT_NOT_FOUND = "cliente no encontrado"
NO_CONCEPT_FOUND = "no se reconoció ningún concepto del catálogo"
OUT_OF_RANGE = "cantidad o número de líneas fuera de rango"

DRAFT_STATUS = "borrador"
CURRENCY = "MXN"
VAT_RATE = Decimal("0.16")
CENTS = Decimal("0.01")
MIN_LINE_QUANTITY = 1
# México centro sin horario de verano: UTC-6 fijo, sin depender de tzdata.
INVOICE_TIMEZONE = timezone(timedelta(hours=-6))

FolioFactory = Callable[[], str]


class InvoiceRejected(Exception):
    """La frase no se puede convertir en factura; el motivo va a la persona.

    :param reason: Uno de los mensajes de negocio en español.
    :type reason: str
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def new_folio() -> str:
    """Genera un folio nuevo (UUID versión 4).

    :return: El folio como texto.
    :rtype: str
    """
    return str(uuid.uuid4())


def money(amount: Decimal) -> str:
    """Redondea a centavos (mitad hacia arriba) y da el texto con 2 decimales.

    :param amount: Cantidad de dinero.
    :type amount: Decimal
    :return: Texto como ``"1740.00"``.
    :rtype: str
    """
    return str(amount.quantize(CENTS, rounding=ROUND_HALF_UP))


def vat_of(subtotal: Decimal) -> Decimal:
    """Calcula el IVA del 16 %, redondeado a centavos mitad hacia arriba.

    :param subtotal: Suma de los importes.
    :type subtotal: Decimal
    :return: El IVA.
    :rtype: Decimal
    """
    return (subtotal * VAT_RATE).quantize(CENTS, rounding=ROUND_HALF_UP)


def is_quantity(value: object) -> bool:
    """Indica si el valor es una cantidad entera (un ``bool`` no cuenta).

    :param value: Valor recibido.
    :type value: object
    :return: ``True`` si es ``int`` y no ``bool``.
    :rtype: bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


class InvoiceService:  # pylint: disable=too-few-public-methods
    """Arma borradores de factura a partir de lo que pide el modelo.

    :param catalog: Catálogo cerrado de clientes y conceptos.
    :type catalog: Catalog
    :param clock: Reloj del que sale la fecha.
    :type clock: Clock
    :param max_lines: Máximo de líneas por factura (``MAX_INVOICE_LINES``).
    :type max_lines: int
    :param max_quantity: Cantidad máxima por línea (``MAX_LINE_QUANTITY``).
    :type max_quantity: int
    :param folio_factory: Generador de folios; por omisión un UUID.
    :type folio_factory: Callable[[], str] or None
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        catalog: Catalog,
        clock: Clock,
        max_lines: int,
        max_quantity: int,
        *,
        folio_factory: Optional[FolioFactory] = None,
    ) -> None:
        self._catalog = catalog
        self._clock = clock
        self._max_lines = max_lines
        self._max_quantity = max_quantity
        self._folio_factory = folio_factory or new_folio

    def create(self, cliente: object, conceptos: object) -> dict:
        """Resuelve, revisa y calcula la factura.

        Orden de las revisiones: cliente, número de líneas y cantidades, y al
        final los conceptos. Los conceptos que no están en el catálogo se
        omiten; si no queda ninguno, se rechaza.

        :param cliente: Texto con el que la frase menciona al cliente.
        :type cliente: object
        :param conceptos: Lista de ``{"concepto": str, "cantidad": int}``.
        :type conceptos: object
        :return: La factura, con el dinero como texto de 2 decimales.
        :rtype: dict
        :raises InvoiceRejected: Con el motivo de negocio en español.
        """
        client = None
        if isinstance(cliente, str):
            client = self._catalog.find_client(cliente)
        if client is None:
            raise InvoiceRejected(CLIENT_NOT_FOUND)
        items = conceptos if isinstance(conceptos, list) else []
        self._check_ranges(items)
        lines = self._resolve_lines(items)
        if not lines:
            raise InvoiceRejected(NO_CONCEPT_FOUND)
        if len(lines) > self._max_lines:
            raise InvoiceRejected(OUT_OF_RANGE)
        return self._build(client, lines)

    def _check_ranges(self, items: Sequence[object]) -> None:
        """Revisa el número de líneas y que cada cantidad esté en rango.

        :param items: Conceptos pedidos por el modelo.
        :type items: Sequence[object]
        :raises InvoiceRejected: Si hay demasiadas líneas o una cantidad no es
            un entero de 1 a ``MAX_LINE_QUANTITY``.
        """
        if len(items) > self._max_lines:
            raise InvoiceRejected(OUT_OF_RANGE)
        for item in items:
            quantity = item.get("cantidad") if isinstance(item, dict) else None
            if not self._quantity_in_range(quantity):
                raise InvoiceRejected(OUT_OF_RANGE)

    def _quantity_in_range(self, quantity: object) -> bool:
        """Indica si la cantidad es un entero de 1 a ``MAX_LINE_QUANTITY``.

        :param quantity: Cantidad pedida.
        :type quantity: object
        :return: ``True`` si está en rango.
        :rtype: bool
        """
        if not is_quantity(quantity):
            return False
        return MIN_LINE_QUANTITY <= int(quantity) <= self._max_quantity  # type: ignore

    def _resolve_lines(self, items: Sequence[object]) -> List[Tuple[Concept, int]]:
        """Resuelve cada concepto contra el catálogo y omite los desconocidos.

        :param items: Conceptos pedidos, con cantidades ya revisadas.
        :type items: Sequence[object]
        :return: Pares de concepto y cantidad.
        :rtype: list[tuple[Concept, int]]
        """
        lines = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("concepto"), str):
                continue
            concept = self._catalog.find_concept(item["concepto"])
            if concept is not None:
                lines.append((concept, int(item["cantidad"])))
        return lines

    def _build(self, client: Client, lines: Sequence[Tuple[Concept, int]]) -> dict:
        """Calcula importes, subtotal, IVA y total, y arma la factura.

        :param client: Cliente resuelto.
        :type client: Client
        :param lines: Conceptos resueltos con su cantidad.
        :type lines: Sequence[tuple[Concept, int]]
        :return: La factura.
        :rtype: dict
        """
        rows = []
        subtotal = Decimal("0")
        for concept, quantity in lines:
            amount = concept.precio_unitario * quantity
            subtotal += amount
            rows.append(
                {
                    "concepto_id": concept.id,
                    "descripcion": concept.descripcion,
                    "unidad": concept.unidad,
                    "cantidad": quantity,
                    "precio_unitario": money(concept.precio_unitario),
                    "importe": money(amount),
                }
            )
        vat = vat_of(subtotal)
        return {
            "folio": self._folio_factory(),
            "fecha": self._clock.now().astimezone(INVOICE_TIMEZONE).date().isoformat(),
            "estado": DRAFT_STATUS,
            "moneda": CURRENCY,
            "cliente": {"id": client.id, "nombre": client.nombre, "rfc": client.rfc},
            "lineas": rows,
            "subtotal": money(subtotal),
            "iva": money(vat),
            "total": money(subtotal + vat),
        }
