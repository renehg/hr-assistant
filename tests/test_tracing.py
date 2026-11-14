"""Pruebas de las trazas opcionales en LangSmith (``app/tracing.py``).

Ninguna prueba se conecta a LangSmith: solo se revisa cuándo se activa el
trazado y qué se ocultaría.
"""

import contextlib
import sys
import types

import pytest

from app.config import load_settings
from app.tracing import is_enabled, redact, request_context, traced


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({"LANGSMITH_TRACING": "true"}, False),
        ({"LANGSMITH_TRACING": "false", "LANGSMITH_API_KEY": "key"}, False),
        ({"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "key"}, True),
    ],
)
def test_tracing_needs_both_the_flag_and_the_key(env, expected):
    assert is_enabled(load_settings(env)) is expected


def test_disabled_tracing_leaves_functions_untouched():
    settings = load_settings({"LANGSMITH_TRACING": "true"})

    def answer():
        return 42

    assert traced(settings, "answer")(answer) is answer
    assert answer() == 42


def test_hidden_payloads_are_sent_empty():
    payload = {"question": "¿Quién es EMP-0004?"}
    assert not redact(True, payload)
    assert redact(False, payload) == payload


ENABLED = {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-key"}


@pytest.fixture
def fake_langsmith(monkeypatch):
    """Reemplaza ``langsmith`` por un módulo falso que guarda las llamadas."""
    calls = {}

    def traceable(**options):
        calls["traceable"] = options
        return lambda function: function

    def tracing_context(**options):
        calls["tracing_context"] = options
        return contextlib.nullcontext()

    module = types.ModuleType("langsmith")
    module.traceable = traceable
    module.tracing_context = tracing_context
    monkeypatch.setitem(sys.modules, "langsmith", module)
    return types.SimpleNamespace(calls=calls)


def test_disabled_tracing_uses_an_empty_request_context(monkeypatch):
    monkeypatch.setitem(sys.modules, "langsmith", None)
    settings = load_settings({})
    with request_context(settings, "req-1", client="acme") as value:
        assert value is None


def test_enabled_tracing_hides_inputs_and_outputs_by_default(fake_langsmith):
    traced(load_settings(ENABLED), "agent_run", run_type="chain")

    options = fake_langsmith.calls["traceable"]
    assert (options["name"], options["run_type"]) == ("agent_run", "chain")
    assert options["process_inputs"]({"question": "¿Quién es EMP-0004?"}) == {}
    assert options["process_outputs"]({"answer": "Jorge Díaz"}) == {}


def test_enabled_tracing_sends_payloads_when_hiding_is_off(fake_langsmith):
    env = dict(ENABLED, HIDE_INPUTS="false", HIDE_OUTPUTS="false")
    traced(load_settings(env), "llm", run_type="llm")

    options = fake_langsmith.calls["traceable"]
    assert options["process_inputs"]({"messages": 1}) == {"messages": 1}
    assert options["process_outputs"]({"text": "ok"}) == {"text": "ok"}


def test_enabled_request_context_puts_request_id_and_client_but_never_the_key(
    fake_langsmith,
):
    secret = "acme-key-that-must-stay-hidden"
    settings = load_settings(dict(ENABLED, API_KEYS=f"acme:{secret}"))
    with request_context(settings, "req-9", client="acme"):
        pass
    call = fake_langsmith.calls["tracing_context"]
    assert call == {"metadata": {"request_id": "req-9", "client": "acme"}}
    assert secret not in repr(call)
