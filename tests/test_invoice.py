"""Pruebas de las reglas de negocio de la factura (``app/invoice.py``).

También cubren la herramienta ``crear_factura`` (``app/invoice_agent.py``):
el cliente debe aparecer en la frase y solo cuenta la primera llamada.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.clock import FixedClock
from app.invoice import (
    CLIENT_NOT_FOUND,
    NO_CONCEPT_FOUND,
    OUT_OF_RANGE,
    InvoiceRejected,
    InvoiceService,
    money,
    vat_of,
)
from app.invoice_agent import ALREADY_USED, InvoiceTool

FOLIO = "F-0001"
# 03:00 en UTC ya es el día anterior en México (UTC-6).
MOMENT = datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)


@pytest.fixture
def service(catalog):
    """Servicio con el catálogo real, reloj fijo y los límites por omisión."""
    return InvoiceService(
        catalog, FixedClock(MOMENT), 5, 1000, folio_factory=lambda: FOLIO
    )


def _line(concepto, cantidad):
    return {"concepto": concepto, "cantidad": cantidad}


def _reason(service, cliente, conceptos):
    with pytest.raises(InvoiceRejected) as raised:
        service.create(cliente, conceptos)
    return raised.value.reason


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("0.125", "0.13"), ("2.675", "2.68"), ("2.004", "2.00"), ("1740", "1740.00")],
)
def test_money_rounds_half_up_to_two_decimals(amount, expected):
    assert money(Decimal(amount)) == expected


def test_vat_rounds_half_cents_up():
    assert vat_of(Decimal("0.03125")) == Decimal("0.01")
    assert vat_of(Decimal("10.03")) == Decimal("1.60")


def test_invoice_is_calculated_with_decimal_and_money_as_text(service):
    invoice = service.create("Ferretería López", [_line("licencia", 1)])

    assert (invoice["subtotal"], invoice["iva"], invoice["total"]) == (
        "1500.00",
        "240.00",
        "1740.00",
    )
    (line,) = invoice["lineas"]
    assert line["concepto_id"] == "CON-003"
    assert (line["precio_unitario"], line["importe"]) == ("1500.00", "1500.00")
    assert invoice["cliente"] == {
        "id": "CLI-001",
        "nombre": "Ferretería López SA de CV",
        "rfc": "FLO010101AB1",
    }
    assert (invoice["folio"], invoice["fecha"]) == (FOLIO, "2026-01-14")
    assert (invoice["estado"], invoice["moneda"]) == ("borrador", "MXN")


@pytest.mark.parametrize(
    ("quantity", "accepted"),
    [(0, False), (1, True), (1000, True), (1001, False), (True, False), (2.5, False)],
    ids=["zero", "one", "max", "over_max", "bool", "float"],
)
def test_quantity_must_be_an_integer_from_1_to_the_maximum(
    service, quantity, accepted
):
    lines = [_line("soporte", quantity)]
    if accepted:
        assert service.create("ferreteria lopez", lines)["lineas"][0]["cantidad"] == (
            quantity
        )
    else:
        assert _reason(service, "ferreteria lopez", lines) == OUT_OF_RANGE


def test_six_lines_are_out_of_range(service):
    lines = [_line("soporte", 1)] * 6
    assert _reason(service, "ferreteria lopez", lines) == OUT_OF_RANGE


def test_unknown_concept_is_skipped_when_another_is_known(service):
    invoice = service.create(
        "ferreteria lopez", [_line("unicornio", 2), _line("timbres", 2)]
    )

    assert [line["concepto_id"] for line in invoice["lineas"]] == ["CON-004"]
    assert invoice["total"] == "812.00"


def test_no_known_concept_is_rejected(service):
    reason = _reason(service, "ferreteria lopez", [_line("unicornio", 1)])
    assert reason == NO_CONCEPT_FOUND


@pytest.mark.parametrize(
    ("cliente", "conceptos", "expected"),
    [
        ("Cliente Fantasma", [_line("unicornio", 0)], CLIENT_NOT_FOUND),
        (None, [_line("soporte", 1)], CLIENT_NOT_FOUND),
        ("ferreteria lopez", [_line("unicornio", 0)], OUT_OF_RANGE),
        ("ferreteria lopez", "no es lista", NO_CONCEPT_FOUND),
    ],
    ids=["client_before_range", "client_not_text", "range_before_concept", "no_list"],
)
def test_rejections_check_client_then_ranges_then_concepts(
    service, cliente, conceptos, expected
):
    assert _reason(service, cliente, conceptos) == expected


def _tool(service, catalog, phrase):
    return InvoiceTool(service, catalog, phrase, mask_for_model=True)


def test_client_that_is_not_in_the_phrase_is_not_found(service, catalog):
    tool = _tool(service, catalog, "Factura a Clínica Dental Sonrisa 1 licencia")

    output = tool.crear_factura("Ferretería López", [_line("licencia", 1)])

    assert output == "error: " + CLIENT_NOT_FOUND
    assert tool.outcome.rejection == CLIENT_NOT_FOUND
    assert tool.outcome.invoice is None


def test_second_call_to_crear_factura_is_ignored(service, catalog):
    tool = _tool(service, catalog, "Factura a Ferretería López 1 licencia")

    first = tool.crear_factura("Ferretería López", [_line("licencia", 1)])
    second = tool.crear_factura("Ferretería López", [_line("soporte", 9)])

    assert json.loads(first)["total"] == "1740.00"
    assert "FLO010101AB1" not in first
    assert second == ALREADY_USED
    assert tool.outcome.invoice["total"] == "1740.00"
    assert tool.outcome.invoice["cliente"]["rfc"] == "FLO010101AB1"
