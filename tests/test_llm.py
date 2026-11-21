"""Pruebas del modelo simulado y sus reglas deterministas.

Contrato del reto de facturación: ``build_models(settings, directory)`` sigue
funcionando; si no recibe catálogo, el simulado lo lee de ``CLIENTES_PATH`` y
``CONCEPTOS_PATH``. Con un mensaje de sistema ``[factura]`` responde
``crear_factura`` con los alias encontrados en la frase.
"""

import json

import pytest

from app.config import load_settings
from app.llm import build_models


@pytest.fixture
def fake_model(directory):
    """Modelo simulado pequeño, construido como lo hace la aplicación."""
    settings = load_settings({})
    return build_models(settings, directory)[settings.model_small]


def _user(content):
    return {"role": "user", "content": content}


def test_tool_result_takes_priority_over_employee_id(fake_model):
    result = '{"id": "EMP-0004", "name": "Jorge Díaz"}'
    completion = fake_model.complete([_user("Resultado de la herramienta: " + result)])
    assert json.loads(completion.text) == {"answer": "Según el directorio: " + result}


def test_employee_id_takes_priority_over_department(fake_model):
    completion = fake_model.complete([_user("¿EMP-0001 trabaja en Ventas?")])
    request = json.loads(completion.text)
    assert request == {"tool": "get_employee", "args": {"employee_id": "EMP-0001"}}


def test_tokens_are_counted_by_words(fake_model):
    messages = [
        {"role": "user", "content": "uno dos tres"},
        {"role": "assistant", "content": "cuatro cinco"},
    ]
    completion = fake_model.complete(messages)
    assert completion.input_tokens == 5
    assert completion.output_tokens == len(completion.text.split())


def _invoice(phrase):
    """Conversación del agente de facturación: sistema ``[factura]`` y la frase."""
    return [{"role": "system", "content": "[factura] Crea borradores."}, _user(phrase)]


def test_invoice_mode_turns_the_phrase_into_a_crear_factura_request(fake_model):
    phrase = (
        "Fáctrale a Ferretería López 10 horas de consultoría fiscal "
        "y 2 paquetes de timbres"
    )
    request = json.loads(fake_model.complete(_invoice(phrase)).text)
    assert request == {
        "tool": "crear_factura",
        "args": {
            "cliente": "ferreteria lopez",
            "conceptos": [
                {"concepto": "consultoria fiscal", "cantidad": 10},
                {"concepto": "paquetes de timbres", "cantidad": 2},
            ],
        },
    }


def test_invoice_mode_without_client_or_number_uses_empty_client_and_one(
    fake_model,
):
    phrase = "Factura a Cliente Fantasma una licencia mensual y 3 horas de soporte"
    request = json.loads(fake_model.complete(_invoice(phrase)).text)
    assert request["args"] == {
        "cliente": "",
        "conceptos": [
            {"concepto": "licencia mensual", "cantidad": 1},
            {"concepto": "soporte", "cantidad": 3},
        ],
    }


def test_fake_provider_builds_two_named_models_that_answer_alike(directory):
    settings = load_settings({})
    models = build_models(settings, directory)
    small, large = models[settings.model_small], models[settings.model_large]
    assert set(models) == {
        "@cf/meta/llama-3.1-8b-instruct-fast",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    }
    assert (small.name, large.name) == (settings.model_small, settings.model_large)
    messages = [_user("¿Quién es EMP-0004?")]
    assert small.complete(messages) == large.complete(messages)
    assert small.complete(messages).cached is False
