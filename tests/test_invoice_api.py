"""Pruebas de ``POST /invoice``: validación de salida, mínimo privilegio y límites.

Usan ``make_invoice_app`` de ``conftest.py``: reloj y folio fijos, modelos que
guardan lo que reciben y un ``invoice_service`` que se puede inyectar.
"""

import json

from app.completion import Completion
from app.config import load_settings

FIXED_FOLIO = "00000000-0000-4000-8000-000000000001"
OUT_OF_RANGE = "cantidad o número de líneas fuera de rango"


class TamperedInvoiceService:  # pylint: disable=too-few-public-methods
    """Servicio de facturas que devuelve un IVA alterado."""

    def create(self, cliente, conceptos):  # pylint: disable=unused-argument
        """Devuelve una factura cuyo IVA y total no cuadran con el subtotal."""
        return {
            "folio": FIXED_FOLIO,
            "fecha": "2026-01-15",
            "estado": "borrador",
            "moneda": "MXN",
            "cliente": {
                "id": "CLI-004",
                "nombre": "Clínica Dental Sonrisa SC",
                "rfc": "CDS040404GH4",
            },
            "lineas": [
                {
                    "concepto_id": "CON-002",
                    "descripcion": "Soporte técnico",
                    "unidad": "hora",
                    "cantidad": 4,
                    "precio_unitario": "600.00",
                    "importe": "2400.00",
                }
            ],
            "subtotal": "2400.00",
            "iva": "999.00",
            "total": "3399.00",
        }


class EmployeeSnoopingModel:  # pylint: disable=too-few-public-methods
    """Modelo que intenta usar una herramienta del directorio de empleados."""

    name = "fake"

    def complete(self, messages):
        """Primero pide ``get_employee``; después responde sin herramienta."""
        if len(messages) <= 2:
            text = json.dumps(
                {"tool": "get_employee", "args": {"employee_id": "EMP-0004"}}
            )
        else:
            text = json.dumps({"answer": "listo"})
        return Completion(text=text, input_tokens=1, output_tokens=1)


def _audits(app, action):
    """Eventos ``audit`` con la acción indicada."""
    return [
        event
        for event in app.events()
        if event["event"] == "audit" and event.get("action") == action
    ]


def test_invoice_that_fails_validation_is_never_returned(make_invoice_app):
    app = make_invoice_app(invoice_service=TamperedInvoiceService())

    response = app.client.post(
        "/invoice", json={"text": "Cobra a Clínica Dental Sonrisa 4 horas de soporte"}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "invoice failed validation"
    assert "invoice" not in response.json()
    (audit,) = _audits(app, "invoice_rejected")
    assert "invoice failed validation" in json.dumps(audit)
    assert not _audits(app, "invoice_created")


def test_invoice_agent_cannot_call_the_employee_directory(make_invoice_app):
    settings = load_settings({})
    snooper = EmployeeSnoopingModel()
    names = (settings.model_small, settings.model_large)
    app = make_invoice_app(models={name: snooper for name in names})

    response = app.client.post(
        "/invoice", json={"text": "Factura a Ferretería López 1 licencia"}
    )

    assert response.status_code == 422
    assert "no existe" in app.model_text()
    assert "Jorge" not in app.model_text()
    assert not _audits(app, "tool_call")


def test_too_many_lines_are_rejected(make_invoice_app):
    app = make_invoice_app(MAX_INVOICE_LINES="1")

    response = app.client.post(
        "/invoice",
        json={"text": "Factura a Ferretería López 1 licencia y 2 horas de soporte"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == OUT_OF_RANGE


def test_home_page_has_the_invoice_section_without_inner_html(make_invoice_app):
    page = make_invoice_app().client.get("/").text
    for test_id in ("invoice-text", "invoice-send", "invoice-result"):
        assert f'data-testid="{test_id}"' in page
    assert "innerHTML" not in page
