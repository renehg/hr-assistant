"""Pruebas de las reglas de compliance (``app/compliance.py``).

Contrato que fijan estas pruebas: ``production_violations(settings)`` devuelve
una lista de textos, uno por regla incumplida. Cada texto nombra la variable
de entorno de la regla (``MODEL_PROVIDER``, ``API_KEYS``, ``HIDE_INPUTS`` o
``HIDE_OUTPUTS``) y nunca incluye una clave. Fuera de ``production`` la lista
siempre está vacía.
"""

import dataclasses

import pytest

from app.compliance import production_violations
from app.config import load_settings

LONG_KEY = "acme-key-long-enough-0123"
SAFE_ENV = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc-123",
    "CF_GATEWAY_ID": "hr-gateway",
    "CF_API_TOKEN": "tok-super-secret-999",
    "API_KEYS": f"acme:{LONG_KEY}",
    "LANGSMITH_TRACING": "true",
    "LANGSMITH_API_KEY": "lsv2-test-key",
    "HIDE_INPUTS": "true",
    "HIDE_OUTPUTS": "true",
}


def _production(**changes):
    """Configuración segura de producción con los cambios indicados."""
    base = load_settings(SAFE_ENV)
    return dataclasses.replace(base, environment="production", **changes)


def test_development_ignores_the_production_rules():
    settings = load_settings({"LANGSMITH_TRACING": "true", "HIDE_INPUTS": "false"})
    assert settings.model_provider == "fake"
    violations = production_violations(settings)
    assert isinstance(violations, list)
    assert not violations


@pytest.mark.parametrize(
    ("changes", "variable"),
    [
        ({"model_provider": "fake"}, "MODEL_PROVIDER"),
        ({"api_keys": {"acme": "short-key-1234"}}, "API_KEYS"),
        ({"hide_inputs": False}, "HIDE_INPUTS"),
        ({"hide_outputs": False}, "HIDE_OUTPUTS"),
    ],
    ids=["fake model", "short key", "visible trace inputs", "visible trace outputs"],
)
def test_each_unsafe_production_setting_is_reported_without_values(
    changes, variable
):
    settings = _production(**changes)
    violations = production_violations(settings)
    assert len(violations) == 1
    assert variable in violations[0]
    for key in settings.api_keys.values():
        assert key not in violations[0]
