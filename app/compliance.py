"""Reglas de compliance que se revisan solas al arrancar en producción.

Cada regla incumplida se describe con el nombre de su variable de entorno, sin
valores. No importa ``app.config`` en tiempo de ejecución para evitar un ciclo:
``load_settings`` llama a este módulo.
"""

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:  # pragma: no cover
    from app.config import Settings

ENVIRONMENT_PRODUCTION = "production"
FORBIDDEN_PRODUCTION_PROVIDER = "fake"
MIN_API_KEY_CHARS = 16


def _key_violations(settings: "Settings") -> List[str]:
    """Revisa que haya claves y que todas tengan el largo mínimo.

    :param settings: Configuración a revisar.
    :type settings: Settings
    :return: Las reglas de ``API_KEYS`` incumplidas.
    :rtype: list[str]
    """
    if not settings.api_keys:
        return ["API_KEYS must define at least one client in production"]
    short = sum(
        1 for key in settings.api_keys.values() if len(key) < MIN_API_KEY_CHARS
    )
    if short:
        return [
            f"API_KEYS has {short} key(s) shorter than {MIN_API_KEY_CHARS} "
            "characters in production"
        ]
    return []


def _tracing_violations(settings: "Settings") -> List[str]:
    """Revisa que las trazas encendidas oculten entradas y salidas.

    :param settings: Configuración a revisar.
    :type settings: Settings
    :return: Las reglas de ``HIDE_INPUTS`` y ``HIDE_OUTPUTS`` incumplidas.
    :rtype: list[str]
    """
    if not settings.langsmith_tracing:
        return []
    found = []
    if not settings.hide_inputs:
        found.append("HIDE_INPUTS must be true when tracing is on in production")
    if not settings.hide_outputs:
        found.append("HIDE_OUTPUTS must be true when tracing is on in production")
    return found


def production_violations(settings: "Settings") -> List[str]:
    """Lista las reglas de producción que la configuración incumple.

    Fuera de ``ENVIRONMENT=production`` no se aplica ninguna regla.

    :param settings: Configuración a revisar.
    :type settings: Settings
    :return: Un texto por regla incumplida, con el nombre de su variable y
        nunca con una clave; vacía si todo está bien.
    :rtype: list[str]
    """
    if settings.environment != ENVIRONMENT_PRODUCTION:
        return []
    found = []
    if settings.model_provider == FORBIDDEN_PRODUCTION_PROVIDER:
        found.append("MODEL_PROVIDER must not be fake in production")
    found.extend(_key_violations(settings))
    found.extend(_tracing_violations(settings))
    return found
