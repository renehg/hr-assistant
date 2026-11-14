"""Pasos de los escenarios de ``features/observability.feature``."""

import json
import sys
import uuid

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/observability.feature")

QUESTION = "¿Quién es EMP-0004?"


@pytest.fixture
def context():
    """Estado compartido entre los pasos de un escenario."""
    return {}


def _events_for(context, request_id):
    """Eventos del log que llevan el ``request_id`` indicado."""
    return [
        event
        for event in context["app"].events()
        if event.get("request_id") == request_id
    ]


def _decoded_log(context):
    """Todo el log como texto, con los acentos ya decodificados."""
    return json.dumps(context["app"].events(), ensure_ascii=False)


@given("the observed HR assistant is running")
def observed_assistant(context, make_observed_app):
    """Levanta la API con reloj, logger y métricas de prueba."""
    context["app"] = make_observed_app()


@given("the observed HR assistant is running with a broken model")
def observed_assistant_with_broken_model(context, make_observed_app, broken_model):
    """Levanta la API con un modelo que siempre lanza una excepción."""
    context["app"] = make_observed_app(model=broken_model)


@given(
    parsers.parse(
        "the observed HR assistant is running with requests that take "
        "{seconds:d} seconds"
    )
)
def observed_slow_assistant(context, make_observed_app, seconds):
    """Levanta la API con un reloj que hace lenta cada petición."""
    context["app"] = make_observed_app(step_seconds=float(seconds))


@given("the observed HR assistant is running with tracing on and no API key")
def observed_assistant_tracing_without_key(context, make_observed_app, monkeypatch):
    """Pide trazas sin clave y hace imposible importar ``langsmith``.

    Si el producto intentara cargar el SDK, la importación fallaría y la
    petición terminaría en 500.
    """
    monkeypatch.setitem(sys.modules, "langsmith", None)
    context["app"] = make_observed_app(LANGSMITH_TRACING="true")


@when("I check the health of the service")
def check_health(context):
    """Consulta ``/health`` sin mandar ``X-Request-ID``."""
    context["response"] = context["app"].client.get("/health")


@when(
    parsers.parse(
        "I check the health of the service with a request id of {length:d} characters"
    )
)
def check_health_with_long_id(context, length):
    """Consulta ``/health`` con un ``X-Request-ID`` demasiado largo."""
    context["unsafe_id"] = "x" * length
    context["response"] = context["app"].client.get(
        "/health", headers={"X-Request-ID": context["unsafe_id"]}
    )


@when("I ask an empty question")
def ask_empty_question(context):
    """Envía una pregunta vacía, que la API debe rechazar."""
    context["response"] = context["app"].client.post("/ask", json={"question": ""})


@when(parsers.parse('I ask "{question}" with the request id "{request_id}"'))
def ask_with_request_id(context, question, request_id):
    """Envía una pregunta con un ``X-Request-ID`` propio."""
    context["question"] = question
    context["response"] = context["app"].client.post(
        "/ask", json={"question": question}, headers={"X-Request-ID": request_id}
    )


@when("I read the metrics")
def read_metrics(context):
    """Consulta ``GET /metrics``."""
    response = context["app"].client.get("/metrics")
    assert response.status_code == 200
    context["metrics"] = response.json()


@when("I open the home page")
def open_home_page(context):
    """Abre la página web."""
    context["response"] = context["app"].client.get("/")


@then("the response carries a generated UUID request id")
def response_has_uuid(context):
    """El encabezado ``X-Request-ID`` es un UUID válido."""
    assert uuid.UUID(context["response"].headers["X-Request-ID"])


@then(parsers.parse('the response header request id is "{request_id}"'))
def header_request_id_is(context, request_id):
    """El encabezado devuelve el id indicado."""
    assert context["response"].headers["X-Request-ID"] == request_id


@then(parsers.parse('the response body request id is "{request_id}"'))
def body_request_id_is(context, request_id):
    """El cuerpo de ``/ask`` devuelve el id indicado."""
    assert context["response"].status_code == 200
    assert context["response"].json()["request_id"] == request_id


@then(
    parsers.parse(
        'the log has the events "request", "agent_run" and "audit" for "{request_id}"'
    )
)
def log_has_events(context, request_id):
    """El log une la petición, la corrida y la herramienta con el mismo id."""
    events = _events_for(context, request_id)
    names = [event["event"] for event in events]
    assert {"request", "agent_run", "audit"} <= set(names)
    for event in events:
        assert event["service"] == "hr-assistant"
        assert event["ts"]
    request_event = next(e for e in events if e["event"] == "request")
    assert request_event["method"] == "POST"
    assert request_event["path"] == "/ask"
    assert request_event["status"] == 200
    assert request_event["latency_ms"] >= 0
    run_event = next(e for e in events if e["event"] == "agent_run")
    assert run_event["steps"] == 2
    assert run_event["tools"] == ["get_employee"]
    assert run_event["stopped"] == "answer"
    assert run_event["question_chars"] == len(context["question"])
    assert run_event["history_messages"] == 0


@then(parsers.parse('the audit event records the tool "{tool}" with its arguments'))
def audit_records_tool(context, tool):
    """El evento ``audit`` dice qué herramienta se llamó y con qué argumentos."""
    audits = [e for e in context["app"].events() if e["event"] == "audit"]
    assert len(audits) == 1
    assert audits[0]["action"] == "tool_call"
    assert audits[0]["tool"] == tool
    assert audits[0]["args"] == {"employee_id": "EMP-0004"}


@then("the log does not contain the question or the answer")
def log_has_no_texts(context):
    """Ni la pregunta ni la respuesta aparecen en el log."""
    answer = context["response"].json()["answer"]
    log_text = _decoded_log(context)
    assert context["question"] not in log_text
    assert answer not in log_text
    assert "Jorge Díaz" not in log_text


@then(parsers.parse('the response is a generic internal error for "{request_id}"'))
def generic_internal_error(context, request_id):
    """Un error interno responde 500 sin detalles y con el id."""
    response = context["response"]
    assert response.status_code == 500
    assert response.json() == {"detail": "internal error", "request_id": request_id}
    assert response.headers["X-Request-ID"] == request_id


@then(
    parsers.parse(
        'the log has an error event of type "{error_type}" without its message'
    )
)
def error_event_without_message(context, error_type, broken_model):
    """El evento ``error`` lleva el tipo de la excepción, nunca su mensaje."""
    errors = [e for e in context["app"].events() if e["event"] == "error"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == error_type
    assert errors[0]["request_id"] == "boom-1"
    assert broken_model.SECRET_MESSAGE not in _decoded_log(context)


@then(parsers.parse("the metrics count {count:d} request"))
def metrics_count_requests(context, count):
    """``/metrics`` cuenta las peticiones previas del proceso."""
    assert context["metrics"]["requests"] == count
    assert context["metrics"]["error_rate"] == 0
    assert isinstance(context["metrics"]["pid"], int)


@then("the metrics tokens match the answer tokens")
def metrics_tokens_match(context):
    """Los tokens de ``/metrics`` suman los de la respuesta."""
    body = context["response"].json()
    tokens = context["metrics"]["tokens"]
    assert tokens == {"input": body["input_tokens"], "output": body["output_tokens"]}


@then(parsers.parse("the SLO target is {target:d} ms and it is met"))
def slo_is_met(context, target):
    """Con peticiones rápidas el SLO se cumple."""
    slo = context["metrics"]["slo"]
    assert slo == {"p95_ms_target": target, "met": True}


@then("the SLO is not met")
def slo_is_not_met(context):
    """Con peticiones de 3 segundos el p95 supera la meta de 2000 ms."""
    metrics = context["metrics"]
    assert metrics["latency_ms"]["p95"] >= 3000
    assert metrics["slo"]["met"] is False


@then("the page has a place for the request id")
def page_shows_request_id(context):
    """La página web pinta el ``request_id`` de cada respuesta."""
    assert context["response"].status_code == 200
    assert "request_id" in context["response"].text


@then("the log uses the generated request id instead of the unsafe one")
def log_uses_generated_id(context):
    """El evento ``request`` lleva el UUID y el id inseguro no aparece."""
    generated = context["response"].headers["X-Request-ID"]
    request_events = [e for e in context["app"].events() if e["event"] == "request"]
    assert [e["request_id"] for e in request_events] == [generated]
    assert context["unsafe_id"] not in _decoded_log(context)


@then(parsers.parse("the response status is {status:d}"))
def response_status_is(context, status):
    """La respuesta tiene el código HTTP indicado."""
    assert context["response"].status_code == status


@then(
    parsers.parse(
        "the log has a request event with status {status:d} for that request id"
    )
)
def log_has_request_with_status(context, status):
    """El rechazo también queda en el log con el id de la respuesta."""
    request_id = context["response"].headers["X-Request-ID"]
    events = _events_for(context, request_id)
    assert [e["event"] for e in events] == ["request"]
    assert events[0]["status"] == status
    assert events[0]["path"] == "/ask"


@then("the metrics error rate is above 0")
def metrics_error_rate_above_zero(context):
    """Tras un 500 la tasa de errores deja de ser cero."""
    assert context["metrics"]["requests"] == 1
    assert context["metrics"]["error_rate"] > 0


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(context, text):
    """La respuesta de ``/ask`` contiene el texto indicado."""
    assert context["response"].status_code == 200
    assert text in context["response"].json()["answer"]
