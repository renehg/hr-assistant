"""API web sin estado del HR Assistant, con request id, log JSON, métricas y costo.

Desde la sesión 4 ``POST /ask`` y ``GET /metrics`` piden una clave por cliente
en ``X-API-Key`` y tienen un límite de peticiones por cliente.
"""

import functools
import os
import uuid
from pathlib import Path
from typing import Awaitable, Callable, List, Literal, Mapping, Optional, Union

from fastapi import Depends, FastAPI, HTTPException, Request, Response, Security
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator

from app.agent import Agent
from app.clock import Clock, SystemClock
from app.config import Settings, load_settings
from app.directory import EmployeeDirectory
from app.gateway import ModelUnavailableError
from app.llm import LanguageModel, build_models
from app.logging_json import JsonLogger
from app.metrics import Metrics
from app.pricing import PriceTable
from app.rate_limit import RateLimiter
from app.router import choose_route
from app.security import ApiKeyAuthenticator
from app.tracing import request_context, traced

INDEX_PATH = Path(__file__).resolve().parent / "static" / "index.html"
REQUEST_ID_HEADER = "X-Request-ID"
API_KEY_HEADER = "X-API-Key"
UNAUTHORIZED_STATUS = 401
UNAUTHORIZED_DETAIL = "invalid or missing API key"
RATE_LIMITED_STATUS = 429
RATE_LIMITED_DETAIL = "rate limit exceeded"
RETRY_AFTER_HEADER = "Retry-After"
MAX_REQUEST_ID_CHARS = 128
INTERNAL_ERROR_STATUS = 500
INTERNAL_ERROR_DETAIL = "internal error"
MODEL_UNAVAILABLE_STATUS = 502
MODEL_UNAVAILABLE_DETAIL = "model unavailable"
MILLISECONDS = 1000
LATENCY_DECIMALS = 3


class HistoryMessage(BaseModel):
    """Mensaje previo de la conversación, enviado por el cliente.

    :param role: ``user`` o ``assistant``.
    :type role: str
    :param content: Texto del mensaje.
    :type content: str
    """

    role: Literal["user", "assistant"]
    content: str


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``.

    :param answer: Respuesta en español.
    :type answer: str
    :param steps: Vueltas del bucle usadas.
    :type steps: int
    :param tools_used: Herramientas ejecutadas.
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada.
    :type input_tokens: int
    :param output_tokens: Tokens de salida.
    :type output_tokens: int
    :param model: Modelo que respondió.
    :type model: str
    :param route: Motivo del enrutador para elegir ese modelo.
    :type route: str
    :param cached_calls: Llamadas servidas desde la caché del gateway.
    :type cached_calls: int
    :param cost_usd: Costo de la respuesta en USD, sin redondear.
    :type cost_usd: float
    :param request_id: Id de la petición, para citarlo a soporte.
    :type request_id: str
    """

    answer: str
    steps: int
    tools_used: List[str]
    input_tokens: int
    output_tokens: int
    model: str
    route: str
    cached_calls: int
    cost_usd: float
    request_id: str


def _build_request_model(max_question_chars: int) -> type:
    """Crea el modelo de entrada con el largo máximo configurado.

    :param max_question_chars: Largo máximo de la pregunta.
    :type max_question_chars: int
    :return: Clase Pydantic para el cuerpo de ``POST /ask``.
    :rtype: type
    """

    class AskRequest(BaseModel):
        """Cuerpo de ``POST /ask``."""

        question: str = Field(min_length=1, max_length=max_question_chars)
        history: List[HistoryMessage] = Field(default_factory=list)

        @field_validator("question")
        @classmethod
        def _question_not_blank(cls, value: str) -> str:
            """Rechaza preguntas formadas solo por espacios."""
            if not value.strip():
                raise ValueError("question must not be blank")
            return value

    return AskRequest


def resolve_request_id(raw: Optional[str]) -> str:
    """Usa el id del cliente si es seguro; si no, genera un UUID.

    Es seguro si no está vacío, tiene hasta 128 caracteres y todos son ASCII
    imprimibles (sin saltos de línea).

    :param raw: Valor del encabezado ``X-Request-ID`` o ``None``.
    :type raw: str or None
    :return: El id a usar en la petición.
    :rtype: str
    """
    if (
        raw
        and len(raw) <= MAX_REQUEST_ID_CHARS
        and raw.isascii()
        and raw.isprintable()
    ):
        return raw
    return str(uuid.uuid4())


def _install_observability(
    application: FastAPI, clock: Clock, logger: JsonLogger, metrics: Metrics
) -> None:
    """Agrega el middleware de request id, log de peticiones y errores.

    :param application: Aplicación a la que se agrega el middleware.
    :type application: FastAPI
    :param clock: Reloj para medir la latencia.
    :type clock: Clock
    :param logger: Logger de eventos ``request`` y ``error``.
    :type logger: JsonLogger
    :param metrics: Métricas del proceso.
    :type metrics: Metrics
    """

    @application.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Asigna el id, mide la petición y convierte errores en un 500."""
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        start = clock.monotonic()
        try:
            response = await call_next(request)
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Solo el tipo: el mensaje puede traer datos personales.
            logger.emit("error", request_id, error_type=type(error).__name__)
            response = JSONResponse(
                {"detail": INTERNAL_ERROR_DETAIL, "request_id": request_id},
                status_code=INTERNAL_ERROR_STATUS,
            )
        latency_ms = round((clock.monotonic() - start) * MILLISECONDS, LATENCY_DECIMALS)
        metrics.record_request(response.status_code, latency_ms)
        logger.emit(
            "request",
            request_id,
            # Solo el nombre del cliente autenticado; la clave nunca se guarda.
            client=getattr(request.state, "client", None),
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _checked_models(
    settings: Settings, models: Mapping[str, LanguageModel]
) -> Mapping[str, LanguageModel]:
    """Comprueba que haya un modelo para ``MODEL_SMALL`` y otro para ``MODEL_LARGE``.

    :param settings: Configuración validada.
    :type settings: Settings
    :param models: Modelos por nombre.
    :type models: Mapping[str, LanguageModel]
    :return: Los mismos modelos.
    :rtype: Mapping[str, LanguageModel]
    :raises ValueError: Si falta alguno de los dos.
    """
    for name in (settings.model_small, settings.model_large):
        if name not in models:
            raise ValueError(f"no model was given for {name!r}")
    return models


def _client_dependency(
    authenticator: ApiKeyAuthenticator, rate_limiter: RateLimiter
) -> Callable[..., str]:
    """Crea la dependencia que identifica al cliente y aplica su límite.

    Corre antes de validar el cuerpo, así que una petición sin clave responde
    ``401`` aunque el cuerpo sea inválido.

    :param authenticator: Buscador del cliente por su clave.
    :type authenticator: ApiKeyAuthenticator
    :param rate_limiter: Límite de peticiones por cliente.
    :type rate_limiter: RateLimiter
    :return: Dependencia de FastAPI que devuelve el nombre del cliente.
    :rtype: Callable
    """
    api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

    def require_client(
        request: Request, api_key: Optional[str] = Security(api_key_header)
    ) -> str:
        """Devuelve el cliente de ``X-API-Key`` o responde ``401`` o ``429``."""
        client = authenticator.client_for(api_key)
        if client is None:
            # El detalle es fijo: nunca repite la clave recibida.
            raise HTTPException(
                status_code=UNAUTHORIZED_STATUS, detail=UNAUTHORIZED_DETAIL
            )
        request.state.client = client
        retry_after = rate_limiter.check(client)
        if retry_after is not None:
            raise HTTPException(
                status_code=RATE_LIMITED_STATUS,
                detail=RATE_LIMITED_DETAIL,
                headers={RETRY_AFTER_HEADER: str(retry_after)},
            )
        return client

    return require_client


def _model_unavailable(request_id: str) -> JSONResponse:
    """Respuesta ``502`` cuando el modelo real no responde.

    :param request_id: Id de la petición.
    :type request_id: str
    :return: ``{"detail": "model unavailable", "request_id": ...}``.
    :rtype: JSONResponse
    """
    return JSONResponse(
        {"detail": MODEL_UNAVAILABLE_DETAIL, "request_id": request_id},
        status_code=MODEL_UNAVAILABLE_STATUS,
    )


def create_app(  # pylint: disable=too-many-arguments,too-many-locals
    settings: Optional[Settings] = None,
    models: Optional[Mapping[str, LanguageModel]] = None,
    directory: Optional[EmployeeDirectory] = None,
    *,
    clock: Optional[Clock] = None,
    logger: Optional[JsonLogger] = None,
    metrics: Optional[Metrics] = None,
    prices: Optional[PriceTable] = None,
    rate_limiter: Optional[RateLimiter] = None,
) -> FastAPI:
    """Crea la aplicación con sus dependencias inyectadas.

    Las dependencias que falten se construyen desde las variables de entorno.
    ``POST /ask`` y ``GET /metrics`` piden ``X-API-Key``; ``/``, ``/health`` y
    ``/docs`` no.

    :param settings: Configuración validada.
    :type settings: Settings or None
    :param models: Modelos por nombre (``MODEL_SMALL`` y ``MODEL_LARGE``).
    :type models: Mapping[str, LanguageModel] or None
    :param directory: Directorio de empleados.
    :type directory: EmployeeDirectory or None
    :param clock: Reloj para el log y las latencias.
    :type clock: Clock or None
    :param logger: Logger JSON; por omisión escribe en la salida estándar.
    :type logger: JsonLogger or None
    :param metrics: Métricas del proceso.
    :type metrics: Metrics or None
    :param prices: Tabla de precios; por omisión se lee de ``PRICES_PATH``.
    :type prices: PriceTable or None
    :param rate_limiter: Límite por cliente; por omisión usa
        ``RATE_LIMIT_PER_MINUTE`` con su propio reloj del sistema.
    :type rate_limiter: RateLimiter or None
    :return: La aplicación FastAPI.
    :rtype: FastAPI
    :raises ValueError: Si falta el modelo pequeño o el grande.
    """
    settings = settings or load_settings()
    directory = directory or EmployeeDirectory(settings.employees_path)
    clock = clock or SystemClock()
    logger = logger or JsonLogger(service=settings.service_name, clock=clock)
    metrics = metrics or Metrics(slo_p95_ms=settings.slo_p95_ms)
    models = _checked_models(settings, models or build_models(settings, directory))
    agent = Agent(
        model=models[settings.model_large],
        directory=directory,
        max_steps=settings.agent_max_steps,
        logger=logger,
        tracer=functools.partial(traced, settings),
        prices=prices or PriceTable.from_file(settings.prices_path),
        history_window=settings.history_window,
    )
    index_html = INDEX_PATH.read_text(encoding="utf-8")
    ask_request = _build_request_model(settings.max_question_chars)
    require_client = _client_dependency(
        ApiKeyAuthenticator(settings.api_keys),
        rate_limiter
        or RateLimiter(settings.rate_limit_per_minute, clock=SystemClock()),
    )

    application = FastAPI(title="HR Assistant")
    _install_observability(application, clock, logger, metrics)

    @application.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        """Sirve la página web."""
        return HTMLResponse(index_html)

    @application.get("/health")
    def health() -> dict:
        """Indica que la copia está viva y su id de proceso."""
        return {"status": "ok", "pid": os.getpid()}

    @application.get("/metrics", dependencies=[Depends(require_client)])
    def read_metrics() -> dict:
        """Devuelve las métricas de este proceso (pide ``X-API-Key``)."""
        return metrics.snapshot()

    @application.post("/ask", response_model=AskResponse)
    def ask(
        body: ask_request,  # type: ignore
        request: Request,
        client: str = Depends(require_client),
    ) -> Union[AskResponse, JSONResponse]:
        """Responde una pregunta sin guardar nada entre peticiones.

        Pide ``X-API-Key``. El enrutador elige el modelo; si el modelo real
        falla responde ``502``.
        """
        request_id = request.state.request_id
        history = [message.model_dump() for message in body.history]
        route = choose_route(body.question, settings)
        try:
            with request_context(settings, request_id, client=client):
                result = agent.run(
                    body.question,
                    history,
                    request_id=request_id,
                    model=models[route.model],
                    route=route,
                    client=client,
                )
        except ModelUnavailableError as error:
            # Solo el tipo: el mensaje no debe llegar al log.
            logger.emit("error", request_id, error_type=type(error).__name__)
            return _model_unavailable(request_id)
        metrics.record_tokens(result.input_tokens, result.output_tokens)
        metrics.record_cost(result.cost_usd)
        return AskResponse(
            answer=result.answer,
            steps=result.steps,
            tools_used=list(result.tools_used),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            model=result.model,
            route=result.route,
            cached_calls=result.cached_calls,
            cost_usd=result.cost_usd,
            request_id=request_id,
        )

    return application


app = create_app()
