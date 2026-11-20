"""Pruebas de la validación de salida (``app/invoice_validation.py``).

Se parte de una factura correcta armada por el servicio y se altera un campo a
la vez: cada alteración debe hacer fallar la validación.
"""

from datetime import datetime, timezone

import pytest

from app.clock import FixedClock
from app.invoice import InvoiceService
from app.invoice_validation import InvoiceValidationError, validate_invoice

MAX_LINES = 5
MAX_QUANTITY = 1000


@pytest.fixture
def invoice(catalog):
    """Factura válida: 2 licencias y 3 horas de soporte para Ferretería López."""
    service = InvoiceService(
        catalog,
        FixedClock(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)),
        MAX_LINES,
        MAX_QUANTITY,
        folio_factory=lambda: "F-0001",
    )
    return service.create(
        "ferreteria lopez",
        [
            {"concepto": "licencia", "cantidad": 2},
            {"concepto": "soporte", "cantidad": 3},
        ],
    )


def test_a_correct_invoice_passes_validation(invoice, catalog):
    assert invoice["total"] == "5568.00"
    validate_invoice(invoice, catalog, MAX_LINES, MAX_QUANTITY)


def _set(*path_and_value):
    *path, value = path_and_value

    def change(invoice):
        target = invoice
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


def _drop(key):
    return lambda invoice: invoice.pop(key)


@pytest.mark.parametrize(
    "alter",
    [
        _set("lineas", 0, "importe", "3001.00"),
        _set("subtotal", "4800.01"),
        _set("iva", "768.01"),
        _set("total", "5568.01"),
        _set("cliente", "id", "CLI-999"),
        _set("lineas", 1, "concepto_id", "CON-999"),
        _set("lineas", 0, "precio_unitario", "1.00"),
        _set("total", 5568.0),
        _drop("iva"),
    ],
    ids=[
        "importe",
        "subtotal",
        "iva",
        "total",
        "unknown_client",
        "unknown_concept",
        "unit_price",
        "total_not_text",
        "missing_field",
    ],
)
def test_each_altered_field_fails_validation(invoice, catalog, alter):
    alter(invoice)

    with pytest.raises(InvoiceValidationError) as raised:
        validate_invoice(invoice, catalog, MAX_LINES, MAX_QUANTITY)

    assert "FLO010101AB1" not in str(raised.value)
