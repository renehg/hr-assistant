"""Pasos de los escenarios de ``features/ask.feature``."""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/ask.feature")


@pytest.fixture
def context():
    """Estado compartido entre los pasos de un escenario."""
    return {}


@given("the HR assistant is running")
def running_assistant(context, make_client):
    """Levanta la API con la configuración por omisión."""
    context["client"] = make_client()


@given(parsers.parse("the HR assistant is running with a step cap of {steps:d}"))
def running_assistant_with_cap(context, make_client, steps):
    """Levanta la API con un tope de vueltas propio."""
    context["client"] = make_client(AGENT_MAX_STEPS=str(steps))


@when(parsers.parse('I ask "{question}"'))
def ask_question(context, question):
    """Envía una pregunta sin historial."""
    context["response"] = context["client"].post("/ask", json={"question": question})


@when(parsers.parse('I ask "{question}" twice'))
def ask_question_twice(context, question):
    """Envía la misma pregunta dos veces seguidas."""
    client = context["client"]
    context["responses"] = [
        client.post("/ask", json={"question": question}) for _ in range(2)
    ]


@when(parsers.parse("I send a question of {length:d} characters"))
def send_question_of_length(context, length):
    """Envía una pregunta con el largo indicado."""
    question = "a" * length
    context["response"] = context["client"].post("/ask", json={"question": question})


def _body(context):
    response = context["response"]
    assert response.status_code == 200
    return response.json()


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(context, text):
    """La respuesta contiene el texto indicado."""
    assert text in _body(context)["answer"]


@then(parsers.parse('the answer is "{text}"'))
def answer_is(context, text):
    """La respuesta es exactamente el texto indicado."""
    assert _body(context)["answer"] == text


@then("the answer says the employee does not exist")
def answer_says_not_found(context):
    """La respuesta dice que el empleado no existe."""
    assert "no existe" in _body(context)["answer"].lower()


@then(parsers.parse('the tools used are "{tool}"'))
def tools_used_are(context, tool):
    """El agente usó exactamente esa herramienta."""
    assert _body(context)["tools_used"] == [tool]


@then("no tools were used")
def no_tools_used(context):
    """El agente no usó herramientas."""
    assert _body(context)["tools_used"] == []


@then(parsers.parse("the agent took {steps:d} steps"))
def agent_took_steps(context, steps):
    """El agente dio el número de vueltas indicado."""
    assert _body(context)["steps"] == steps


@then("the request is rejected as invalid")
def request_rejected(context):
    """La API rechaza la petición con 422."""
    assert context["response"].status_code == 422


@then("both responses are identical")
def responses_identical(context):
    """Dos peticiones iguales dan la misma respuesta, salvo su ``request_id``."""
    first, second = context["responses"]
    assert first.status_code == second.status_code == 200
    first_body, second_body = first.json(), second.json()
    assert first_body.pop("request_id") != second_body.pop("request_id")
    assert first_body == second_body
