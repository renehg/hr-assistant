"""Pasos de los escenarios de ``features/costs.feature``."""

import copy
import json

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import load_settings
from app.llm import build_models

scenarios("features/costs.feature")

SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
MODEL_BY_SIZE = {"small": SMALL_MODEL, "large": LARGE_MODEL}
BASE_QUESTION = "¿Quién es EMP-0004?"


class RecordingModel:  # pylint: disable=too-few-public-methods
    """Envuelve un modelo y guarda una copia de los mensajes que recibe."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def complete(self, messages):
        """Guarda los mensajes y delega en el modelo envuelto."""
        self.calls.append(copy.deepcopy(list(messages)))
        return self._inner.complete(messages)


@pytest.fixture
def context():
    """Estado compartido entre los pasos de un escenario."""
    return {"answers": []}


def _ask(context, question, history=None, request_id=None):
    """Envía una pregunta y guarda la respuesta."""
    headers = {"X-Request-ID": request_id} if request_id else {}
    response = context["app"].client.post(
        "/ask", json={"question": question, "history": history or []}, headers=headers
    )
    context["response"] = response
    if response.status_code == 200:
        context["answers"].append(response.json())


@given("the HR assistant is running with the default settings")
def assistant_with_defaults(context, make_observed_app):
    """Levanta la API con los modelos simulados y la configuración por omisión."""
    context["app"] = make_observed_app()


@given("the HR assistant is running with routing disabled")
def assistant_without_routing(context, make_observed_app):
    """Levanta la API con ``ROUTING=false``."""
    context["app"] = make_observed_app(ROUTING="false")


@given(
    parsers.parse(
        "the HR assistant is running with a recording model and a history window "
        "of {window:d}"
    )
)
def assistant_with_recording_model(context, make_observed_app, directory, window):
    """Levanta la API con un modelo que guarda lo que recibe."""
    settings = load_settings({"HISTORY_WINDOW": str(window)})
    fake = build_models(settings, directory)[settings.model_small]
    context["model"] = RecordingModel(fake)
    context["app"] = make_observed_app(
        model=context["model"], HISTORY_WINDOW=str(window)
    )


@given("the HR assistant is running with a gateway that fails")
def assistant_with_failing_gateway(
    context, make_observed_app, make_gateway_models, gateway_env
):
    """Levanta la API con un gateway que responde 500 a todo."""
    models, _ = make_gateway_models(lambda request: httpx.Response(500))
    context["app"] = make_observed_app(models=models, **gateway_env)


@given("the HR assistant is running with a gateway that answers from its cache")
def assistant_with_cached_gateway(
    context, make_observed_app, make_gateway_models, gateway_env, reply
):
    """Levanta la API con un gateway que responde siempre desde su caché."""
    answer = json.dumps({"answer": "Hola, ¿en qué te ayudo?"})
    models, _ = make_gateway_models(
        lambda request: reply(answer, headers={"cf-aig-cache-status": "HIT"}),
        CACHE_TTL_SECONDS="60",
    )
    context["app"] = make_observed_app(
        models=models, CACHE_TTL_SECONDS="60", **gateway_env
    )


@when(parsers.re(r'I ask "(?P<question>[^"]+)"'))
def ask_question(context, question):
    """Envía una pregunta sin historial."""
    _ask(context, question)


@when(parsers.re(r'I ask "(?P<question>[^"]+)" with the request id "(?P<rid>[^"]+)"'))
def ask_with_request_id(context, question, rid):
    """Envía una pregunta con un ``X-Request-ID`` propio."""
    _ask(context, question, request_id=rid)


@when(
    parsers.re(
        r'I ask "(?P<question>[^"]+)" after a history of (?P<count>\d+) messages'
    )
)
def ask_after_history(context, question, count):
    """Envía una pregunta con un historial numerado de ``count`` mensajes."""
    roles = ("user", "assistant")
    context["history"] = [
        {"role": roles[index % 2], "content": f"mensaje {index}"}
        for index in range(int(count))
    ]
    _ask(context, question, history=context["history"])


@when(
    parsers.parse("I ask a question of {length:d} characters without keywords")
)
def ask_question_of_length(context, length):
    """Envía una pregunta sin palabras clave, rellenada hasta ``length``."""
    question = BASE_QUESTION + " " + "x" * (length - len(BASE_QUESTION) - 1)
    assert len(question) == length
    _ask(context, question)


@when("I read the metrics")
def read_metrics(context):
    """Consulta ``GET /metrics``."""
    response = context["app"].client.get("/metrics")
    assert response.status_code == 200
    context["metrics"] = response.json()


@then(parsers.parse('the answer used the {size} model with the route "{route}"'))
def answer_used_model(context, size, route):
    """La respuesta dice qué modelo eligió el enrutador y por qué."""
    assert context["response"].status_code == 200
    body = context["response"].json()
    assert body["model"] == MODEL_BY_SIZE[size]
    assert body["route"] == route


@then(parsers.parse("the answer cost is above 0 with {cached:d} cached calls"))
def answer_cost_above_zero(context, cached):
    """La respuesta tiene un costo positivo y el conteo de caché indicado."""
    assert context["response"].status_code == 200
    body = context["response"].json()
    assert body["cost_usd"] > 0
    assert body["cached_calls"] == cached


@then(parsers.parse("the answer cost is 0 with {cached:d} cached calls"))
def answer_cost_is_zero(context, cached):
    """Una respuesta servida desde la caché no cuesta."""
    assert context["response"].status_code == 200
    body = context["response"].json()
    assert body["cost_usd"] == 0
    assert body["cached_calls"] == cached


@then(
    parsers.parse(
        "the model received only the last {window:d} history messages before "
        "the question"
    )
)
def model_received_window(context, window):
    """Cada llamada al modelo empieza con los últimos mensajes del historial."""
    assert context["response"].status_code == 200
    first_call = context["model"].calls[0]
    assert first_call[:-1] == context["history"][-window:]
    assert first_call[-1] == {"role": "user", "content": BASE_QUESTION}


@then("the metrics cost is the sum of the answer costs")
def metrics_cost_is_sum(context):
    """``/metrics`` acumula el costo de todas las respuestas."""
    expected = sum(answer["cost_usd"] for answer in context["answers"])
    assert len(context["answers"]) == 2
    assert context["metrics"]["cost_usd"] == pytest.approx(expected)
    assert context["metrics"]["cost_usd"] > 0


@then(
    parsers.parse(
        'the response is "{detail}" with status {status:d} for "{request_id}"'
    )
)
def response_is_error(context, detail, status, request_id):
    """El fallo del modelo responde con el detalle y el id de la petición."""
    response = context["response"]
    assert response.status_code == status
    assert response.json() == {"detail": detail, "request_id": request_id}
    assert response.headers["X-Request-ID"] == request_id
