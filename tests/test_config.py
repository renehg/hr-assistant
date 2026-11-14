"""Pruebas de la configuración leída de variables de entorno."""

from pathlib import Path

import pytest

from app.config import load_settings


def test_defaults_are_used_when_environment_is_empty():
    settings = load_settings({})
    assert settings.model_provider == "fake"
    assert settings.agent_max_steps == 3
    assert settings.max_question_chars == 2000
    assert Path(settings.employees_path).name == "employees.json"
    assert Path(settings.employees_path).is_file()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AGENT_MAX_STEPS", "0"),
        ("MODEL_PROVIDER", "openai"),
        ("EMPLOYEES_PATH", "missing/nowhere.json"),
        ("SLO_P95_MS", "fast"),
        ("SLO_P95_MS", "0"),
        ("RATE_LIMIT_PER_MINUTE", "0"),
        ("ENVIRONMENT", "prod"),
    ],
)
def test_invalid_setting_stops_startup_with_clear_message(name, value):
    with pytest.raises(ValueError, match=name):
        load_settings({name: value})


def test_observability_settings_have_safe_defaults():
    settings = load_settings({})
    assert settings.service_name == "hr-assistant"
    assert settings.slo_p95_ms == 2000
    assert settings.langsmith_tracing is False
    assert settings.hide_inputs is True
    assert settings.hide_outputs is True


def test_boolean_settings_ignore_case():
    settings = load_settings(
        {"LANGSMITH_TRACING": "TRUE", "HIDE_INPUTS": "False", "HIDE_OUTPUTS": "false"}
    )
    assert settings.langsmith_tracing is True
    assert settings.hide_inputs is False
    assert settings.hide_outputs is False


@pytest.mark.parametrize(
    "name", ["LANGSMITH_TRACING", "HIDE_INPUTS", "HIDE_OUTPUTS"]
)
def test_invalid_boolean_setting_stops_startup(name):
    with pytest.raises(ValueError, match=name):
        load_settings({name: "yes"})


def test_service_name_and_slo_target_can_be_configured():
    settings = load_settings({"SERVICE_NAME": "hr-staging", "SLO_P95_MS": "500"})
    assert settings.service_name == "hr-staging"
    assert settings.slo_p95_ms == 500


def test_cost_settings_have_the_defaults_of_the_spec():
    settings = load_settings({})
    assert settings.model_small == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert settings.model_large == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert settings.routing is True
    assert settings.router_max_chars == 80
    assert settings.history_window == 6
    assert settings.model_max_tokens == 300
    assert settings.model_temperature == 0
    assert settings.cache_ttl_seconds == 0
    assert Path(settings.prices_path).name == "model_prices.json"
    assert (settings.cf_account_id, settings.cf_gateway_id) == ("", "default")
    assert settings.cf_api_token == ""


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ROUTING", "maybe"),
        ("ROUTER_MAX_CHARS", "0"),
        ("HISTORY_WINDOW", "-1"),
        ("MODEL_MAX_TOKENS", "many"),
        ("MODEL_TEMPERATURE", "3"),
        ("CACHE_TTL_SECONDS", "-5"),
        ("PRICES_PATH", "missing/prices.json"),
        ("MODEL_SMALL", "gpt-without-price"),
    ],
)
def test_invalid_cost_setting_stops_startup(name, value):
    with pytest.raises(ValueError, match=name):
        load_settings({name: value})


# CF_GATEWAY_ID tiene valor por omisión ("default"), así que nunca falta.
@pytest.mark.parametrize("missing", ["CF_ACCOUNT_ID", "CF_API_TOKEN"])
def test_gateway_without_a_cloudflare_variable_does_not_start(missing, gateway_env):
    env = {key: value for key, value in gateway_env.items() if key != missing}
    with pytest.raises(ValueError, match=missing) as raised:
        load_settings(env)
    assert "tok-super-secret-999" not in str(raised.value)


def test_cloudflare_token_never_appears_in_settings(gateway_env):
    settings = load_settings(gateway_env)
    assert settings.model_provider == "gateway"
    assert settings.cf_api_token == "tok-super-secret-999"
    assert "tok-super-secret-999" not in repr(settings)
    assert "tok-super-secret-999" not in str(settings)


def test_production_settings_have_the_defaults_of_the_spec():
    settings = load_settings({})
    assert settings.environment == "development"
    assert not settings.api_keys
    assert settings.rate_limit_per_minute == 30


def test_client_api_keys_are_kept_but_never_appear_in_settings():
    secret = "acme-key-that-must-stay-hidden"
    settings = load_settings({"API_KEYS": f"acme:{secret}"})
    assert dict(settings.api_keys) == {"acme": secret}
    assert secret not in repr(settings)
    assert secret not in str(settings)


def test_langsmith_key_never_appears_in_settings():
    secret = "lsv2-super-secret-key"
    settings = load_settings({"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": secret})
    assert secret not in repr(settings)
    assert secret not in str(settings)
