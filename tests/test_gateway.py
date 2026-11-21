"""Pruebas del cliente de AI Gateway (``app/gateway.py``) sin red."""

import json

import httpx
import pytest

from app.gateway import ModelUnavailableError

SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
EXPECTED_URL = (
    "https://gateway.ai.cloudflare.com/v1/acc-123/hr-gateway/"
    "workers-ai/v1/chat/completions"
)
ANSWER = json.dumps({"answer": "Hola"})
QUESTION = [{"role": "user", "content": "Hola"}]


def test_call_uses_the_gateway_url_token_body_and_usage(make_gateway_models, reply):
    models, requests = make_gateway_models(
        lambda request: reply(ANSWER, prompt_tokens=42, completion_tokens=7),
        MODEL_MAX_TOKENS="120",
    )

    completion = models[SMALL_MODEL].complete(QUESTION)

    (request,) = requests
    body = json.loads(request.content)
    assert str(request.url) == EXPECTED_URL
    assert request.headers["Authorization"] == "Bearer tok-super-secret-999"
    assert "cf-aig-cache-ttl" not in request.headers
    assert body["model"] == SMALL_MODEL
    assert body["messages"][-1] == QUESTION[-1]
    assert (body["max_tokens"], body["temperature"]) == (120, 0)
    assert (completion.text, completion.input_tokens) == (ANSWER, 42)
    assert (completion.output_tokens, completion.cached) == (7, False)


def test_cache_ttl_is_sent_and_a_hit_is_marked_as_cached(make_gateway_models, reply):
    models, requests = make_gateway_models(
        lambda request: reply(ANSWER, headers={"cf-aig-cache-status": "HIT"}),
        CACHE_TTL_SECONDS="300",
    )

    completion = models[SMALL_MODEL].complete(QUESTION)

    assert requests[0].headers["cf-aig-cache-ttl"] == "300"
    assert completion.cached is True


def test_own_system_message_replaces_the_hr_prompt(make_gateway_models, reply):
    models, requests = make_gateway_models(lambda request: reply(ANSWER))
    invoice_system = {"role": "system", "content": "[factura] reglas de facturación"}

    models[SMALL_MODEL].complete([invoice_system, *QUESTION])
    models[SMALL_MODEL].complete(QUESTION)

    own, default = (json.loads(request.content)["messages"] for request in requests)
    assert own == [invoice_system, *QUESTION]
    assert default[0]["role"] == "system"
    assert "Recursos Humanos" in default[0]["content"]


def _timeout(request):
    raise httpx.ReadTimeout("timed out", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, text="upstream error"),
        lambda request: httpx.Response(200, text="this is not json"),
        lambda request: httpx.Response(200, json={"choices": []}),
        _timeout,
    ],
    ids=["server_error", "invalid_json", "missing_usage", "timeout"],
)
def test_gateway_failures_raise_model_unavailable_without_the_token(
    make_gateway_models, handler
):
    models, _ = make_gateway_models(handler)

    with pytest.raises(ModelUnavailableError) as raised:
        models[SMALL_MODEL].complete(QUESTION)

    assert "tok-super-secret-999" not in str(raised.value)
