"""Pasos de los escenarios de ``features/security.feature``.

La aplicación se levanta sin clave por omisión (``api_key=None``): cada paso
decide qué clave manda en ``X-API-Key``.
"""

import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import load_settings

scenarios("features/security.feature")

API_KEY_HEADER = "X-API-Key"
PUBLIC_ROUTES = ("/", "/health", "/docs")


@pytest.fixture
def context():
    """Estado compartido entre los pasos de un escenario."""
    return {"responses": []}


def _log_text(context):
    """Todo el log: el texto crudo y los eventos con acentos decodificados."""
    app = context["app"]
    return app.stream.getvalue() + json.dumps(app.events(), ensure_ascii=False)


def _ask_as(context, client_keys, client, question, request_id=None):
    """Envía una pregunta con la clave del cliente indicado."""
    headers = {API_KEY_HEADER: client_keys[client]}
    if request_id:
        headers["X-Request-ID"] = request_id
    response = context["app"].client.post(
        "/ask", json={"question": question}, headers=headers
    )
    context["responses"].append(response)
    context["response"] = response
    return response


def _start(context, env):
    """Carga la configuración como lo haría el arranque del producto."""
    context["settings"] = None
    context["error"] = None
    try:
        context["settings"] = load_settings(env)
    except ValueError as error:
        context["error"] = error


@given("the secured HR assistant is running")
def secured_assistant(context, make_observed_app):
    """Levanta la API con dos clientes y un cliente HTTP sin clave."""
    context["app"] = make_observed_app(api_key=None)


@given(
    parsers.parse(
        "the secured HR assistant is running with a limit of {limit:d} requests "
        "per minute"
    )
)
def secured_assistant_with_limit(context, make_observed_app, limit):
    """Levanta la API con un ``RATE_LIMIT_PER_MINUTE`` propio."""
    context["app"] = make_observed_app(
        api_key=None, RATE_LIMIT_PER_MINUTE=str(limit)
    )


@when(parsers.parse('I ask "{question}" without a key'))
def ask_without_key(context, question):
    """Envía una pregunta sin ``X-API-Key``."""
    response = context["app"].client.post("/ask", json={"question": question})
    context["responses"].append(response)
    context["response"] = response


@when(parsers.parse('I ask "{question}" with the key "{key}"'))
def ask_with_key(context, question, key):
    """Envía una pregunta con una clave que no pertenece a ningún cliente."""
    context["response"] = context["app"].client.post(
        "/ask", json={"question": question}, headers={API_KEY_HEADER: key}
    )


@when("I ask an empty question without a key")
def ask_empty_without_key(context):
    """Envía un cuerpo inválido y además sin clave."""
    context["response"] = context["app"].client.post("/ask", json={"question": ""})


@when("I read the metrics without a key")
def read_metrics_without_key(context):
    """Consulta ``GET /metrics`` sin clave."""
    context["responses"].append(context["app"].client.get("/metrics"))


@when("I open the home page, the health check and the docs without a key")
def open_public_routes(context):
    """Consulta las rutas públicas sin clave."""
    client = context["app"].client
    context["responses"] = [client.get(route) for route in PUBLIC_ROUTES]


@when(
    parsers.parse(
        'the client "{client}" asks "{question}" with the request id "{request_id}"'
    )
)
def client_asks_with_request_id(context, client_keys, client, question, request_id):
    """Envía una pregunta con la clave del cliente y un ``X-Request-ID``."""
    _ask_as(context, client_keys, client, question, request_id)


@when(parsers.parse('the client "{client}" asks "{question}" {count:d} times'))
def client_asks_several_times(context, client_keys, client, question, count):
    """Envía la misma pregunta varias veces con la clave del cliente."""
    for _ in range(count):
        _ask_as(context, client_keys, client, question)


@when(parsers.parse("{seconds:d} seconds pass"))
def seconds_pass(context, seconds):
    """Avanza el reloj del limitador."""
    context["app"].limiter_clock.advance(seconds)


@when("the product starts in production with the fake model and no API keys")
def start_production_unsafe(context):
    """Arranca en producción con el modelo simulado y sin claves."""
    _start(
        context,
        {"ENVIRONMENT": "production", "MODEL_PROVIDER": "fake", "API_KEYS": ""},
    )


@when(
    "the product starts in production with the gateway, long keys and hidden traces"
)
def start_production_safe(context, gateway_env):
    """Arranca en producción con todas las reglas de compliance cumplidas."""
    env = dict(
        gateway_env,
        ENVIRONMENT="production",
        API_KEYS="acme:acme-key-long-enough-0123,beta:beta-key-long-enough-4567",
        LANGSMITH_TRACING="true",
        LANGSMITH_API_KEY="lsv2-test-key",
        HIDE_INPUTS="true",
        HIDE_OUTPUTS="true",
    )
    _start(context, env)


@when(parsers.parse('the product starts with API_KEYS "{raw}"'))
def start_with_api_keys(context, raw):
    """Arranca en desarrollo con una ``API_KEYS`` dada."""
    _start(context, {"API_KEYS": raw})


@then(
    parsers.parse('both responses are {status:d} with the detail "{detail}"')
)
def both_responses_are(context, status, detail):
    """Las dos rutas protegidas rechazan la petición igual."""
    assert len(context["responses"]) == 2
    for response in context["responses"]:
        assert response.status_code == status
        assert response.json()["detail"] == detail


@then("the metrics read with a valid key report no errors")
def metrics_report_no_errors(context, client_keys):
    """Los ``401`` cuentan como peticiones, pero no como errores."""
    response = context["app"].client.get(
        "/metrics", headers={API_KEY_HEADER: client_keys["test-suite"]}
    )
    assert response.status_code == 200
    metrics = response.json()
    assert metrics["requests"] == 2
    assert metrics["error_rate"] == 0


@then(parsers.parse('the response is {status:d} with the detail "{detail}"'))
def response_is(context, status, detail):
    """La respuesta tiene el código y el detalle indicados."""
    assert context["response"].status_code == status
    assert context["response"].json()["detail"] == detail


@then(parsers.parse('the log does not contain "{text}"'))
def log_does_not_contain(context, text):
    """El texto indicado no aparece en ninguna línea del log."""
    assert text not in _log_text(context)


@then("every response is 200")
def every_response_is_ok(context):
    """Todas las rutas públicas responden sin pedir clave."""
    assert [r.status_code for r in context["responses"]] == [200] * len(
        PUBLIC_ROUTES
    )


@then(parsers.parse("the response status is {status:d}"))
def response_status_is(context, status):
    """La respuesta tiene el código HTTP indicado."""
    assert context["response"].status_code == status


@then(
    parsers.parse(
        'the events "request", "agent_run" and "audit" for "{request_id}" '
        'name the client "{client}"'
    )
)
def events_name_the_client(context, request_id, client):
    """Los tres eventos de la petición llevan el nombre del cliente."""
    events = [
        event
        for event in context["app"].events()
        if event.get("request_id") == request_id
    ]
    by_name = {event["event"]: event for event in events}
    for name in ("request", "agent_run", "audit"):
        assert by_name[name]["client"] == client


@then(parsers.parse('the log does not contain the key of "{client}"'))
def log_does_not_contain_key(context, client_keys, client):
    """La clave del cliente no aparece en el log."""
    assert client_keys[client] not in _log_text(context)


@then(parsers.parse('the last response is {status:d} with the detail "{detail}"'))
def last_response_is(context, status, detail):
    """La última respuesta tiene el código y el detalle indicados."""
    response = context["responses"][-1]
    assert response.status_code == status
    assert response.json()["detail"] == detail


@then(parsers.parse("the last response says to retry after {seconds:d} seconds"))
def last_response_retry_after(context, seconds):
    """El encabezado ``Retry-After`` dice cuántos segundos faltan."""
    assert context["responses"][-1].headers["Retry-After"] == str(seconds)


@then(parsers.parse('the client "{client}" can still ask "{question}"'))
def other_client_can_ask(context, client_keys, client, question):
    """El límite es por cliente: otro cliente sigue pasando."""
    response = _ask_as(context, client_keys, client, question)
    assert response.status_code == 200


@then(parsers.parse("the last response status is {status:d}"))
def last_response_status_is(context, status):
    """La última respuesta tiene el código indicado."""
    assert context["responses"][-1].status_code == status


@then(parsers.parse('startup fails naming "{first}" and "{second}"'))
def startup_fails_naming_both(context, first, second):
    """El error de arranque nombra todas las reglas incumplidas."""
    assert context["error"] is not None
    message = str(context["error"])
    assert first in message
    assert second in message


@then("startup succeeds in the production environment")
def startup_succeeds(context):
    """Con todo correcto, el producto arranca en producción."""
    assert context["error"] is None
    assert context["settings"].environment == "production"


@then(
    parsers.parse(
        'startup fails naming "{variable}", entry {entry:d} and length {length:d}'
    )
)
def startup_fails_naming_entry(context, variable, entry, length):
    """El error dice qué entrada falla y su largo."""
    assert context["error"] is not None
    message = str(context["error"])
    assert variable in message
    assert str(entry) in message
    assert str(length) in message


@then(parsers.parse('the startup error does not contain "{text}"'))
def startup_error_hides(context, text):
    """El valor de la entrada mal formada nunca aparece en el error."""
    assert text not in str(context["error"])
