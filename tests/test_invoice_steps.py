"""Pasos de los escenarios de ``features/invoice.feature``.

La aplicación usa el modelo simulado, un reloj fijo y un folio fijo. Los
modelos están envueltos para guardar lo que reciben.
"""

import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import load_settings

scenarios("features/invoice.feature")

SAFE_PRODUCTION_ENV = {
    "ENVIRONMENT": "production",
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc-123",
    "CF_GATEWAY_ID": "hr-gateway",
    "CF_API_TOKEN": "tok-super-secret-999",
    "API_KEYS": "acme:acme-key-long-enough-0123",
    "LANGSMITH_TRACING": "true",
    "LANGSMITH_API_KEY": "lsv2-test-key",
    "HIDE_INPUTS": "true",
    "HIDE_OUTPUTS": "true",
}


@pytest.fixture
def context():
    """Estado compartido entre los pasos de un escenario."""
    return {"responses": []}


def _log_text(context):
    """Todo el log: el texto crudo y los eventos con acentos decodificados."""
    app = context["app"]
    return app.stream.getvalue() + json.dumps(app.events(), ensure_ascii=False)


def _post_invoice(context, text):
    """Envía ``POST /invoice`` y guarda la respuesta."""
    response = context["app"].client.post("/invoice", json={"text": text})
    context["responses"].append(response)
    context["response"] = response
    return response


@given("the invoice assistant is running with a fixed clock and folio")
def invoice_assistant(context, make_invoice_app):
    """Levanta la API con la clave del cliente ``test-suite``."""
    context["app"] = make_invoice_app()


@given("the invoice assistant is running without a key")
def invoice_assistant_without_key(context, make_invoice_app):
    """Levanta la API con un cliente HTTP que no manda clave."""
    context["app"] = make_invoice_app(api_key=None)


@when(parsers.parse('I ask for the invoice "{phrase}"'))
def ask_for_invoice(context, phrase):
    """Pide un borrador de factura con la frase indicada."""
    _post_invoice(context, phrase)


@when("I ask for an invoice with an empty phrase")
def ask_for_empty_invoice(context):
    """Pide una factura con el texto vacío."""
    _post_invoice(context, "")


@when(
    parsers.parse(
        'the product starts in production with safe settings but PII_MASKING "{value}"'
    )
)
def start_production_without_masking(context, value):
    """Arranca en producción con todo correcto salvo ``PII_MASKING``."""
    context["error"] = None
    try:
        load_settings({**SAFE_PRODUCTION_ENV, "PII_MASKING": value})
    except ValueError as error:
        context["error"] = error


@then(parsers.parse("the response status is {status:d}"))
def response_status_is(context, status):
    """La respuesta tiene el código HTTP indicado."""
    assert context["response"].status_code == status


@then(parsers.parse('the response is {status:d} with the detail "{detail}"'))
def response_is(context, status, detail):
    """La respuesta tiene el código y el detalle indicados."""
    assert context["response"].status_code == status
    assert context["response"].json()["detail"] == detail


@then(parsers.parse('the invoice is a draft in MXN for the client "{client_id}"'))
def invoice_is_draft(context, client_id):
    """La factura es un borrador en pesos, con folio y fecha fijos."""
    invoice = context["response"].json()["invoice"]
    assert invoice["estado"] == "borrador"
    assert invoice["moneda"] == "MXN"
    assert invoice["cliente"]["id"] == client_id
    assert invoice["folio"] == "00000000-0000-4000-8000-000000000001"
    assert invoice["fecha"].startswith("2026-01-15")


@then(
    parsers.parse(
        'the invoice has subtotal "{subtotal}", VAT "{vat}" and total "{total}"'
    )
)
def invoice_amounts(context, subtotal, vat, total):
    """Los importes van como texto con dos decimales."""
    invoice = context["response"].json()["invoice"]
    assert (invoice["subtotal"], invoice["iva"], invoice["total"]) == (
        subtotal,
        vat,
        total,
    )


@then(parsers.parse('the only tool used is "{tool}"'))
def only_tool_used(context, tool):
    """El agente de facturación solo usó su herramienta."""
    assert context["response"].json()["tools_used"] == [tool]


@then(parsers.parse('an "{event}" audit event gives the reason "{reason}"'))
def audit_event_gives_reason(context, event, reason):
    """El rechazo queda en la auditoría con su motivo y el cliente de la clave."""
    audits = [
        e
        for e in context["app"].events()
        if e["event"] == "audit" and e.get("action") == event
    ]
    assert len(audits) == 1
    assert reason in json.dumps(audits[0], ensure_ascii=False)
    assert audits[0]["client"] == "test-suite"


@then(parsers.parse('the detected personal data is only "{kind}"'))
def detected_personal_data(context, kind):
    """``pii_detected`` lleva solo tipos, nunca valores."""
    assert context["response"].json()["pii_detected"] == [kind]


@then(parsers.parse('the log does not contain "{text}"'))
def log_does_not_contain(context, text):
    """El texto indicado no aparece en ninguna línea del log."""
    assert text not in _log_text(context)


@then(parsers.parse('the model never received "{text}"'))
def model_never_received(context, text):
    """El texto indicado nunca llegó al modelo."""
    assert context["app"].model_calls
    assert text not in context["app"].model_text()


@then(parsers.parse('the model received "{text}"'))
def model_received(context, text):
    """El texto indicado sí llegó al modelo."""
    assert text in context["app"].model_text()


@then("the model was never called")
def model_never_called(context):
    """La validación del cuerpo corta antes de llamar al modelo."""
    assert context["app"].model_calls == []


@then(parsers.parse('the invoice shows the client RFC "{rfc}"'))
def invoice_shows_rfc(context, rfc):
    """La persona autenticada recibe el RFC completo."""
    assert context["response"].status_code == 200
    assert context["response"].json()["invoice"]["cliente"]["rfc"] == rfc


@then(
    parsers.parse(
        "the metrics report {created:d} invoices created, {rejected:d} rejected "
        "and {pii:d} with personal data"
    )
)
def metrics_report(context, created, rejected, pii):
    """``/metrics`` cuenta facturas creadas, rechazadas y peticiones con PII."""
    metrics = context["app"].client.get("/metrics").json()
    assert metrics["invoices_created"] == created
    assert metrics["invoices_rejected"] == rejected
    assert metrics["pii_detected"] == pii


@then(parsers.parse('startup fails naming "{variable}"'))
def startup_fails_naming(context, variable):
    """El error de arranque nombra la variable incumplida."""
    assert context["error"] is not None
    assert variable in str(context["error"])
