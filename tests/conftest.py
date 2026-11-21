"""Fixtures compartidas: directorio real, modelos simulados y cliente de la API.

Desde la sesión 2 también hay un cliente "observado": con reloj, logger y
métricas inyectados, para leer el log JSON y las métricas en las pruebas.

Desde la sesión 3 la aplicación recibe ``models``: un diccionario con un modelo
por nombre (``MODEL_SMALL`` y ``MODEL_LARGE``). Para el gateway hay una fábrica
que usa ``httpx.MockTransport``: ninguna prueba sale a la red.

Desde la sesión 4 ``POST /ask`` y ``GET /metrics`` piden ``X-API-Key``. Todas
las fábricas fijan una ``API_KEYS`` de prueba con dos clientes y, salvo que se
pida lo contrario con ``api_key=None``, el cliente HTTP manda la clave del
cliente ``test-suite`` en cada petición. El limitador de peticiones se inyecta
con su propio reloj manual, separado del reloj de latencias.

Para el reto de facturación hay ``make_invoice_app``: reloj y folio fijos, y
modelos que guardan lo que reciben para revisar el enmascarado de PII.
"""

import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.directory import EmployeeDirectory
from app.llm import build_models
from app.main import create_app

FIXED_MOMENT = datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc)

GATEWAY_ENV = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc-123",
    "CF_GATEWAY_ID": "hr-gateway",
    "CF_API_TOKEN": "tok-super-secret-999",
}

TEST_CLIENT = "test-suite"
OTHER_CLIENT = "other-team"
CLIENT_KEYS = {
    TEST_CLIENT: "test-suite-key-0123456789",
    OTHER_CLIENT: "other-team-key-9876543210",
}
TEST_API_KEY = CLIENT_KEYS[TEST_CLIENT]
TEST_API_KEYS = ",".join(f"{name}:{key}" for name, key in CLIENT_KEYS.items())
API_KEY_HEADER = "X-API-Key"


def with_test_keys(env):
    """Agrega la ``API_KEYS`` de prueba, salvo que la prueba fije la suya.

    :param env: Variables de entorno de la prueba.
    :return: Las mismas variables con ``API_KEYS``.
    """
    return {"API_KEYS": TEST_API_KEYS, **env}


def key_headers(api_key):
    """Encabezados por omisión del cliente HTTP.

    :param api_key: Clave a mandar o ``None`` para no mandar ninguna.
    :return: ``{"X-API-Key": api_key}`` o un diccionario vacío.
    """
    return {API_KEY_HEADER: api_key} if api_key else {}


class ManualClock:
    """Reloj de prueba que solo avanza cuando la prueba lo pide.

    Lo usa el limitador de peticiones: la prueba decide cuánto tiempo pasa.
    """

    def __init__(self) -> None:
        self._elapsed = 0.0

    def now(self) -> datetime:
        """Devuelve el momento fijo más el tiempo que se ha avanzado."""
        return FIXED_MOMENT + timedelta(seconds=self._elapsed)

    def monotonic(self) -> float:
        """Devuelve 1000 más los segundos avanzados."""
        return 1000.0 + self._elapsed

    def advance(self, seconds: float) -> None:
        """Avanza el reloj ``seconds`` segundos."""
        self._elapsed += seconds


class SteppingClock:
    """Reloj de prueba: hora fija y un reloj monotónico que avanza a saltos.

    :param step_seconds: Segundos que avanza ``monotonic()`` en cada llamada.
    :type step_seconds: float
    """

    def __init__(self, step_seconds: float = 0.0) -> None:
        self._step = step_seconds
        self._value = 100.0

    def now(self) -> datetime:
        """Devuelve siempre el mismo momento, en UTC."""
        return FIXED_MOMENT

    def monotonic(self) -> float:
        """Devuelve el valor actual y lo avanza ``step_seconds``."""
        value = self._value
        self._value += self._step
        return value


class BrokenModel:  # pylint: disable=too-few-public-methods
    """Modelo que siempre truena, con un mensaje que no debe llegar al log."""

    SECRET_MESSAGE = "secreto interno de EMP-0004"

    def complete(self, messages):
        """Lanza siempre ``RuntimeError``."""
        raise RuntimeError(self.SECRET_MESSAGE)


@dataclass
class ObservedApp:
    """Cliente de prueba junto con su log y sus métricas.

    :param client: Cliente HTTP de la aplicación.
    :param stream: Flujo donde el logger escribe las líneas JSON.
    :param limiter_clock: Reloj manual del limitador de peticiones.
    """

    client: TestClient
    stream: io.StringIO
    limiter_clock: ManualClock = field(default_factory=ManualClock)

    def events(self):
        """Devuelve los eventos del log ya interpretados como diccionarios."""
        lines = self.stream.getvalue().splitlines()
        return [json.loads(line) for line in lines if line.strip()]


def gateway_reply(content, prompt_tokens=10, completion_tokens=5, headers=None):
    """Arma una respuesta del gateway con el formato compatible con OpenAI.

    :param content: Texto que devuelve el modelo.
    :param prompt_tokens: Valor de ``usage.prompt_tokens``.
    :param completion_tokens: Valor de ``usage.completion_tokens``.
    :param headers: Encabezados extra, por ejemplo ``cf-aig-cache-status``.
    :return: Respuesta HTTP 200 simulada.
    """
    body = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    return httpx.Response(200, json=body, headers=headers or {})


def _models_for(settings, directory, model=None, models=None):
    """Elige los modelos de la aplicación de prueba.

    Si se pasa un solo ``model``, se usa con los dos nombres.
    """
    if models is not None:
        return models
    if model is not None:
        return {settings.model_small: model, settings.model_large: model}
    return build_models(settings, directory)


@pytest.fixture
def directory():
    """Directorio de empleados leído de la ruta por omisión."""
    return EmployeeDirectory(load_settings({}).employees_path)


@pytest.fixture
def catalog():
    """Catálogo real de clientes y conceptos, leído de las rutas por omisión."""
    # pylint: disable=import-outside-toplevel
    from app.catalog import Catalog

    settings = load_settings({})
    return Catalog.from_files(settings.clientes_path, settings.conceptos_path)


@pytest.fixture
def make_client(directory):
    """Fábrica de clientes de prueba con variables de entorno a medida."""

    def _make(**env):
        settings = load_settings(with_test_keys(env))
        app = create_app(
            settings=settings,
            models=_models_for(settings, directory),
            directory=directory,
        )
        return TestClient(app, headers=key_headers(TEST_API_KEY))

    return _make


@pytest.fixture
def client_keys():
    """Clientes de prueba y sus claves, tal como van en ``API_KEYS``."""
    return dict(CLIENT_KEYS)


@pytest.fixture
def manual_clock():
    """Reloj manual que la prueba avanza con ``advance(seconds)``."""
    return ManualClock()


@pytest.fixture
def broken_model():
    """Modelo que lanza una excepción en cuanto se le llama."""
    return BrokenModel()


@pytest.fixture
def gateway_env():
    """Variables de entorno de un gateway de prueba (token falso)."""
    return dict(GATEWAY_ENV)


@pytest.fixture
def reply():
    """La función ``gateway_reply``, para armar respuestas del gateway."""
    return gateway_reply


@pytest.fixture
def make_gateway_models():
    """Fábrica de modelos del gateway con un transporte HTTP simulado.

    Devuelve ``(models, requests)``: los dos modelos por nombre y la lista
    donde se guardan las peticiones que llegaron al transporte.
    """
    # pylint: disable=import-outside-toplevel
    from app.gateway import GatewayModel

    def _make(handler, **env):
        settings = load_settings({**GATEWAY_ENV, **env})
        requests = []

        def _record(request):
            requests.append(request)
            return handler(request)

        client = httpx.Client(transport=httpx.MockTransport(_record))
        models = {
            name: GatewayModel(settings=settings, model=name, client=client)
            for name in (settings.model_small, settings.model_large)
        }
        return models, requests

    return _make


@pytest.fixture
def make_observed_app(directory):
    """Fábrica de aplicaciones con reloj, logger JSON y métricas inyectados.

    ``api_key`` es la clave que el cliente HTTP manda en cada petición; con
    ``None`` no manda ninguna. El limitador usa un ``ManualClock`` propio,
    disponible en ``ObservedApp.limiter_clock``.
    """
    # pylint: disable=import-outside-toplevel
    from app.logging_json import JsonLogger
    from app.metrics import Metrics
    from app.rate_limit import RateLimiter

    def _make(
        model=None,
        models=None,
        step_seconds=0.0,
        api_key: Optional[str] = TEST_API_KEY,
        **env,
    ):
        settings = load_settings(with_test_keys(env))
        clock = SteppingClock(step_seconds)
        limiter_clock = ManualClock()
        stream = io.StringIO()
        logger = JsonLogger(service=settings.service_name, clock=clock, stream=stream)
        metrics = Metrics(slo_p95_ms=settings.slo_p95_ms)
        app = create_app(
            settings=settings,
            models=_models_for(settings, directory, model, models),
            directory=directory,
            clock=clock,
            logger=logger,
            metrics=metrics,
            rate_limiter=RateLimiter(
                limit_per_minute=settings.rate_limit_per_minute, clock=limiter_clock
            ),
        )
        client = TestClient(
            app, raise_server_exceptions=False, headers=key_headers(api_key)
        )
        return ObservedApp(client=client, stream=stream, limiter_clock=limiter_clock)

    return _make


FIXED_FOLIO = "00000000-0000-4000-8000-000000000001"


class RecordingModel:  # pylint: disable=too-few-public-methods
    """Envuelve un modelo y guarda cada conversación que recibe.

    Sirve para comprobar qué vio el modelo (por ejemplo, que la PII llega
    enmascarada).

    :param inner: Modelo real al que se delega.
    :param calls: Lista compartida donde se guardan los mensajes recibidos.
    """

    def __init__(self, inner, calls):
        self._inner = inner
        self._calls = calls
        self.name = getattr(inner, "name", "fake")

    def complete(self, messages):
        """Guarda los mensajes y delega en el modelo envuelto."""
        self._calls.append([dict(message) for message in messages])
        return self._inner.complete(messages)


@dataclass
class InvoiceApp(ObservedApp):
    """Aplicación observada que además guarda lo que recibió el modelo.

    :param model_calls: Conversaciones recibidas por los modelos, en orden.
    """

    model_calls: list = field(default_factory=list)

    def model_text(self):
        """Todo lo que recibió el modelo, como un solo texto."""
        return json.dumps(self.model_calls, ensure_ascii=False)


def _recorded_models(settings, directory, models, calls):
    """Envuelve cada modelo en ``RecordingModel`` para guardar lo que recibe.

    :param settings: Configuración de la aplicación.
    :param directory: Directorio de empleados.
    :param models: Modelos simulados opcionales.
    :param calls: Lista compartida donde se guardan las conversaciones.
    :return: Diccionario de modelos envueltos, por nombre.
    """
    inner = _models_for(settings, directory, models=models)
    return {name: RecordingModel(model, calls) for name, model in inner.items()}


@pytest.fixture
def make_invoice_app(directory):
    """Fábrica de aplicaciones para ``POST /invoice``.

    Contrato que fijan las pruebas: ``create_app`` acepta ``folio_factory``
    (función sin argumentos que devuelve el folio) e ``invoice_service`` (objeto
    con ``create(cliente, conceptos)`` que devuelve la factura como diccionario,
    con el dinero en texto). El reloj es fijo y el folio es ``FIXED_FOLIO``.
    Los modelos simulados se envuelven en ``RecordingModel``.
    """
    # pylint: disable=import-outside-toplevel
    from app.logging_json import JsonLogger
    from app.metrics import Metrics
    from app.rate_limit import RateLimiter

    def _make(
        models=None,
        invoice_service=None,
        api_key: Optional[str] = TEST_API_KEY,
        **env,
    ):
        settings = load_settings(with_test_keys(env))
        clock = SteppingClock()
        limiter_clock = ManualClock()
        stream = io.StringIO()
        logger = JsonLogger(service=settings.service_name, clock=clock, stream=stream)
        metrics = Metrics(slo_p95_ms=settings.slo_p95_ms)
        calls = []
        extra = {"invoice_service": invoice_service} if invoice_service else {}
        app = create_app(
            settings=settings,
            models=_recorded_models(settings, directory, models, calls),
            directory=directory,
            clock=clock,
            logger=logger,
            metrics=metrics,
            rate_limiter=RateLimiter(
                limit_per_minute=settings.rate_limit_per_minute, clock=limiter_clock
            ),
            folio_factory=lambda: FIXED_FOLIO,
            **extra,
        )
        client = TestClient(
            app, raise_server_exceptions=False, headers=key_headers(api_key)
        )
        return InvoiceApp(
            client=client,
            stream=stream,
            limiter_clock=limiter_clock,
            model_calls=calls,
        )

    return _make
