"""Configuración inmutable leída de variables de entorno con valores por omisión."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from app.compliance import ENVIRONMENT_PRODUCTION, production_violations
from app.pricing import PriceTable
from app.security import parse_api_keys

PRODUCT_ROOT = Path(__file__).resolve().parent.parent
PROVIDER_FAKE = "fake"
PROVIDER_GATEWAY = "gateway"
SUPPORTED_PROVIDERS = (PROVIDER_FAKE, PROVIDER_GATEWAY)

DEFAULT_MODEL_PROVIDER = PROVIDER_FAKE
DEFAULT_AGENT_MAX_STEPS = 3
DEFAULT_MAX_QUESTION_CHARS = 2000
DEFAULT_EMPLOYEES_PATH = "data/employees.json"
DEFAULT_SERVICE_NAME = "hr-assistant"
DEFAULT_SLO_P95_MS = 2000
LANGSMITH_KEY_VARIABLE = "LANGSMITH_API_KEY"
TRUE_VALUES = ("true",)
FALSE_VALUES = ("false",)

DEFAULT_CF_GATEWAY_ID = "default"
DEFAULT_MODEL_SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
DEFAULT_MODEL_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_ROUTING = True
DEFAULT_ROUTER_MAX_CHARS = 80
DEFAULT_HISTORY_WINDOW = 6
DEFAULT_MODEL_MAX_TOKENS = 300
DEFAULT_MODEL_TEMPERATURE = 0.0
MIN_MODEL_TEMPERATURE = 0.0
MAX_MODEL_TEMPERATURE = 2.0
DEFAULT_CACHE_TTL_SECONDS = 0
DEFAULT_PRICES_PATH = "data/model_prices.json"
GATEWAY_REQUIRED_VARIABLES = ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN")

ENVIRONMENT_DEVELOPMENT = "development"
SUPPORTED_ENVIRONMENTS = (ENVIRONMENT_DEVELOPMENT, ENVIRONMENT_PRODUCTION)
DEFAULT_ENVIRONMENT = ENVIRONMENT_DEVELOPMENT
DEFAULT_RATE_LIMIT_PER_MINUTE = 30


@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Configuración validada de la aplicación.

    La clave de LangSmith nunca se guarda: solo se registra si existe. El token
    de Cloudflare sí se guarda, pero no aparece en ``repr`` ni en ``str``.

    :param model_provider: Proveedor del modelo: ``fake`` o ``gateway``.
    :type model_provider: str
    :param agent_max_steps: Tope de vueltas del bucle del agente.
    :type agent_max_steps: int
    :param max_question_chars: Largo máximo permitido de la pregunta.
    :type max_question_chars: int
    :param employees_path: Ruta absoluta al archivo de empleados.
    :type employees_path: str
    :param service_name: Valor del campo ``service`` del log.
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos.
    :type slo_p95_ms: int
    :param langsmith_tracing: Si se pidió encender las trazas.
    :type langsmith_tracing: bool
    :param langsmith_key_present: Si existe ``LANGSMITH_API_KEY`` en el entorno.
    :type langsmith_key_present: bool
    :param hide_inputs: No mandar entradas a LangSmith.
    :type hide_inputs: bool
    :param hide_outputs: No mandar salidas a LangSmith.
    :type hide_outputs: bool
    :param cf_account_id: Id de la cuenta de Cloudflare.
    :type cf_account_id: str
    :param cf_gateway_id: Id del AI Gateway.
    :type cf_gateway_id: str
    :param cf_api_token: Token de Cloudflare (secreto, fuera de ``repr``).
    :type cf_api_token: str
    :param model_small: Nombre del modelo barato.
    :type model_small: str
    :param model_large: Nombre del modelo capaz.
    :type model_large: str
    :param routing: Si se elige el modelo por pregunta.
    :type routing: bool
    :param router_max_chars: Largo a partir del cual se usa el modelo capaz.
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan al modelo.
    :type history_window: int
    :param model_max_tokens: Tope de tokens de salida por llamada.
    :type model_max_tokens: int
    :param model_temperature: Temperatura del modelo real.
    :type model_temperature: float
    :param cache_ttl_seconds: Vida de la caché del gateway (0: apagada).
    :type cache_ttl_seconds: int
    :param prices_path: Ruta absoluta al archivo de precios.
    :type prices_path: str
    :param environment: ``development`` o ``production`` (aplica compliance).
    :type environment: str
    :param api_keys: Clave de cada cliente (secreto, fuera de ``repr``).
    :type api_keys: Mapping[str, str]
    :param rate_limit_per_minute: Peticiones por cliente por minuto.
    :type rate_limit_per_minute: int
    """

    model_provider: str
    agent_max_steps: int
    max_question_chars: int
    employees_path: str
    service_name: str = DEFAULT_SERVICE_NAME
    slo_p95_ms: int = DEFAULT_SLO_P95_MS
    langsmith_tracing: bool = False
    langsmith_key_present: bool = False
    hide_inputs: bool = True
    hide_outputs: bool = True
    cf_account_id: str = ""
    cf_gateway_id: str = DEFAULT_CF_GATEWAY_ID
    cf_api_token: str = field(default="", repr=False)
    model_small: str = DEFAULT_MODEL_SMALL
    model_large: str = DEFAULT_MODEL_LARGE
    routing: bool = DEFAULT_ROUTING
    router_max_chars: int = DEFAULT_ROUTER_MAX_CHARS
    history_window: int = DEFAULT_HISTORY_WINDOW
    model_max_tokens: int = DEFAULT_MODEL_MAX_TOKENS
    model_temperature: float = DEFAULT_MODEL_TEMPERATURE
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    prices_path: str = ""
    environment: str = DEFAULT_ENVIRONMENT
    api_keys: Mapping[str, str] = field(
        default_factory=dict, repr=False, hash=False
    )
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    """Lee un booleano ``true`` o ``false`` sin distinguir mayúsculas.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :param name: Nombre de la variable.
    :type name: str
    :param default: Valor por omisión.
    :type default: bool
    :return: El booleano leído.
    :rtype: bool
    :raises ValueError: Si el valor no es ``true`` ni ``false``.
    """
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    folded = raw.strip().casefold()
    if folded in TRUE_VALUES:
        return True
    if folded in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


def _int_at_least(
    env: Mapping[str, str], name: str, default: int, minimum: int
) -> int:
    """Lee un entero mayor o igual a ``minimum``.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :param name: Nombre de la variable.
    :type name: str
    :param default: Valor por omisión.
    :type default: int
    :param minimum: Valor mínimo permitido.
    :type minimum: int
    :return: El entero leído.
    :rtype: int
    :raises ValueError: Si el valor no es un entero o es menor que ``minimum``.
    """
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from error
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Lee un entero mayor o igual a 1.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :param name: Nombre de la variable.
    :type name: str
    :param default: Valor por omisión.
    :type default: int
    :return: El entero leído.
    :rtype: int
    :raises ValueError: Si el valor no es un entero o es menor que 1.
    """
    return _int_at_least(env, name, default, 1)


def _non_negative_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Lee un entero mayor o igual a 0.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :param name: Nombre de la variable.
    :type name: str
    :param default: Valor por omisión.
    :type default: int
    :return: El entero leído.
    :rtype: int
    :raises ValueError: Si el valor no es un entero o es negativo.
    """
    return _int_at_least(env, name, default, 0)


def _temperature(env: Mapping[str, str]) -> float:
    """Lee ``MODEL_TEMPERATURE``, un número entre 0 y 2.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :return: La temperatura.
    :rtype: float
    :raises ValueError: Si no es un número o está fuera del rango.
    """
    name = "MODEL_TEMPERATURE"
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return DEFAULT_MODEL_TEMPERATURE
    try:
        value = float(raw.strip())
    except ValueError as error:
        raise ValueError(f"{name} must be a number, got {raw!r}") from error
    if not MIN_MODEL_TEMPERATURE <= value <= MAX_MODEL_TEMPERATURE:
        raise ValueError(
            f"{name} must be between {MIN_MODEL_TEMPERATURE} and "
            f"{MAX_MODEL_TEMPERATURE}, got {value}"
        )
    return value


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    """Lee un texto sin espacios a los lados; vacío usa el valor por omisión.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :param name: Nombre de la variable.
    :type name: str
    :param default: Valor por omisión.
    :type default: str
    :return: El texto leído.
    :rtype: str
    """
    return (env.get(name) or "").strip() or default


def _existing_file(env: Mapping[str, str], name: str, default: str) -> str:
    """Resuelve y valida la ruta de un archivo de datos.

    Las rutas relativas se resuelven contra la carpeta ``product/``.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :param name: Nombre de la variable con la ruta.
    :type name: str
    :param default: Ruta por omisión.
    :type default: str
    :return: Ruta absoluta existente.
    :rtype: str
    :raises ValueError: Si el archivo no existe.
    """
    path = Path(env.get(name) or default)
    if not path.is_absolute():
        path = PRODUCT_ROOT / path
    if not path.is_file():
        raise ValueError(f"{name} does not point to a file: {path}")
    return str(path)


def _cloudflare_settings(env: Mapping[str, str], provider: str) -> dict:
    """Lee las variables ``CF_*``; con ``gateway`` las tres son obligatorias.

    Los mensajes de error nombran la variable, nunca su valor.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :param provider: Proveedor del modelo ya validado.
    :type provider: str
    :return: ``cf_account_id``, ``cf_gateway_id`` y ``cf_api_token``.
    :rtype: dict
    :raises ValueError: Si falta alguna variable con ``gateway``.
    """
    values = {
        "CF_ACCOUNT_ID": _text(env, "CF_ACCOUNT_ID", ""),
        "CF_GATEWAY_ID": _text(env, "CF_GATEWAY_ID", DEFAULT_CF_GATEWAY_ID),
        "CF_API_TOKEN": _text(env, "CF_API_TOKEN", ""),
    }
    if provider == PROVIDER_GATEWAY:
        for name in GATEWAY_REQUIRED_VARIABLES:
            if not values[name]:
                raise ValueError(f"{name} is required when MODEL_PROVIDER=gateway")
    return {
        "cf_account_id": values["CF_ACCOUNT_ID"],
        "cf_gateway_id": values["CF_GATEWAY_ID"],
        "cf_api_token": values["CF_API_TOKEN"],
    }


def _model_settings(env: Mapping[str, str]) -> dict:
    """Lee los modelos y los precios; cada modelo debe tener precio.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :return: ``model_small``, ``model_large`` y ``prices_path``.
    :rtype: dict
    :raises ValueError: Si los precios no se pueden leer o falta un precio.
    """
    prices_path = _existing_file(env, "PRICES_PATH", DEFAULT_PRICES_PATH)
    try:
        prices = PriceTable.from_file(prices_path)
    except ValueError as error:
        raise ValueError(f"PRICES_PATH is invalid: {error}") from error
    models = {
        "MODEL_SMALL": _text(env, "MODEL_SMALL", DEFAULT_MODEL_SMALL),
        "MODEL_LARGE": _text(env, "MODEL_LARGE", DEFAULT_MODEL_LARGE),
    }
    for name, model in models.items():
        if not prices.has_price(model):
            raise ValueError(f"{name} has no price in PRICES_PATH: {model!r}")
    return {
        "model_small": models["MODEL_SMALL"],
        "model_large": models["MODEL_LARGE"],
        "prices_path": prices_path,
    }


def _cost_settings(env: Mapping[str, str]) -> dict:
    """Lee las palancas de costo.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :return: Valores de enrutamiento, ventana, tope, temperatura y caché.
    :rtype: dict
    :raises ValueError: Si algún valor es inválido.
    """
    return {
        "routing": _boolean(env, "ROUTING", DEFAULT_ROUTING),
        "router_max_chars": _positive_int(
            env, "ROUTER_MAX_CHARS", DEFAULT_ROUTER_MAX_CHARS
        ),
        "history_window": _non_negative_int(
            env, "HISTORY_WINDOW", DEFAULT_HISTORY_WINDOW
        ),
        "model_max_tokens": _positive_int(
            env, "MODEL_MAX_TOKENS", DEFAULT_MODEL_MAX_TOKENS
        ),
        "model_temperature": _temperature(env),
        "cache_ttl_seconds": _non_negative_int(
            env, "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS
        ),
    }


def _environment(env: Mapping[str, str]) -> str:
    """Lee ``ENVIRONMENT``: ``development`` o ``production``.

    Un valor desconocido no arranca, para que un error de escritura no apague
    las reglas de compliance.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :return: El ambiente en minúsculas.
    :rtype: str
    :raises ValueError: Si el valor no es uno de los ambientes conocidos.
    """
    value = _text(env, "ENVIRONMENT", DEFAULT_ENVIRONMENT).casefold()
    if value not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(
            f"ENVIRONMENT must be one of {SUPPORTED_ENVIRONMENTS}, got {value!r}"
        )
    return value


def _access_settings(env: Mapping[str, str]) -> dict:
    """Lee el ambiente, las claves por cliente y el límite de peticiones.

    :param env: Variables de entorno.
    :type env: Mapping[str, str]
    :return: ``environment``, ``api_keys`` y ``rate_limit_per_minute``.
    :rtype: dict
    :raises ValueError: Si algún valor es inválido; los errores de
        ``API_KEYS`` nunca incluyen una clave.
    """
    return {
        "environment": _environment(env),
        "api_keys": parse_api_keys(env.get("API_KEYS")),
        "rate_limit_per_minute": _positive_int(
            env, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE
        ),
    }


def _enforce_compliance(settings: Settings) -> Settings:
    """Se niega a arrancar si la configuración incumple las reglas de producción.

    :param settings: Configuración ya validada.
    :type settings: Settings
    :return: La misma configuración si cumple.
    :rtype: Settings
    :raises ValueError: Si hay reglas incumplidas; el mensaje las nombra todas,
        sin valores.
    """
    violations = production_violations(settings)
    if violations:
        raise ValueError(
            "ENVIRONMENT=production refuses to start: " + "; ".join(violations)
        )
    return settings


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Construye la configuración a partir de variables de entorno.

    Con ``ENVIRONMENT=production`` además aplica las reglas de compliance.

    :param env: Variables a usar; si es ``None`` se usa ``os.environ``.
    :type env: Mapping[str, str] or None
    :return: Configuración validada.
    :rtype: Settings
    :raises ValueError: Si algún valor es inválido o se incumple una regla de
        producción; el mensaje nombra la variable, nunca un secreto.
    """
    source = os.environ if env is None else env
    provider = (source.get("MODEL_PROVIDER") or DEFAULT_MODEL_PROVIDER).strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"MODEL_PROVIDER must be one of {SUPPORTED_PROVIDERS}, got {provider!r}"
        )
    settings = Settings(
        model_provider=provider,
        agent_max_steps=_positive_int(
            source, "AGENT_MAX_STEPS", DEFAULT_AGENT_MAX_STEPS
        ),
        max_question_chars=_positive_int(
            source, "MAX_QUESTION_CHARS", DEFAULT_MAX_QUESTION_CHARS
        ),
        employees_path=_existing_file(
            source, "EMPLOYEES_PATH", DEFAULT_EMPLOYEES_PATH
        ),
        service_name=(source.get("SERVICE_NAME") or DEFAULT_SERVICE_NAME).strip(),
        slo_p95_ms=_positive_int(source, "SLO_P95_MS", DEFAULT_SLO_P95_MS),
        langsmith_tracing=_boolean(source, "LANGSMITH_TRACING", False),
        langsmith_key_present=bool((source.get(LANGSMITH_KEY_VARIABLE) or "").strip()),
        hide_inputs=_boolean(source, "HIDE_INPUTS", True),
        hide_outputs=_boolean(source, "HIDE_OUTPUTS", True),
        **_cloudflare_settings(source, provider),
        **_model_settings(source),
        **_cost_settings(source),
        **_access_settings(source),
    )
    return _enforce_compliance(settings)
