"""Trazas opcionales en LangSmith, privadas por omisión.

Es el único módulo que conoce ``langsmith``. Si el trazado está apagado o falta
``LANGSMITH_API_KEY``, no se importa el SDK ni se abre ninguna conexión. La
clave la lee el SDK directamente del entorno; este módulo nunca la toca.
"""

import contextlib
from typing import Any, Callable, ContextManager, Mapping, Optional, TypeVar

from app.config import Settings

Function = TypeVar("Function", bound=Callable[..., Any])
Decorator = Callable[[Function], Function]


def is_enabled(settings: Settings) -> bool:
    """Indica si hay que mandar trazas a LangSmith.

    :param settings: Configuración validada.
    :type settings: Settings
    :return: ``True`` solo con ``LANGSMITH_TRACING=true`` y la clave presente.
    :rtype: bool
    """
    return settings.langsmith_tracing and settings.langsmith_key_present


def redact(hide: bool, payload: Mapping[str, Any]) -> dict:
    """Devuelve lo que se mandaría a LangSmith según el ocultamiento.

    :param hide: Si se deben ocultar los datos.
    :type hide: bool
    :param payload: Entradas o salidas de la función trazada.
    :type payload: Mapping[str, Any]
    :return: Un diccionario vacío si ``hide``; si no, una copia del original.
    :rtype: dict
    """
    if hide:
        return {}
    return dict(payload)


def _identity(function: Function) -> Function:
    """Decorador nulo: devuelve la misma función.

    :param function: Función a decorar.
    :type function: Callable
    :return: La misma función, sin cambios.
    :rtype: Callable
    """
    return function


def traced(settings: Settings, name: str, run_type: str = "chain") -> Decorator:
    """Crea el decorador de traza para una función.

    :param settings: Configuración validada.
    :type settings: Settings
    :param name: Nombre de la traza en LangSmith.
    :type name: str
    :param run_type: Tipo de corrida (``chain``, ``llm`` o ``tool``).
    :type run_type: str
    :return: ``langsmith.traceable`` con ocultamiento, o un decorador nulo.
    :rtype: Callable
    """
    if not is_enabled(settings):
        return _identity
    # Import tardío: sin trazado activo el SDK ni se carga.
    from langsmith import traceable  # pylint: disable=import-outside-toplevel

    return traceable(
        name=name,
        run_type=run_type,
        process_inputs=lambda inputs: redact(settings.hide_inputs, inputs),
        process_outputs=lambda outputs: redact(settings.hide_outputs, outputs),
    )


def request_context(
    settings: Settings, request_id: str, client: Optional[str] = None
) -> ContextManager[Any]:
    """Contexto que pone ``request_id`` y ``client`` en los metadatos de las trazas.

    Solo recibe el nombre del cliente: la clave nunca llega a la traza.

    :param settings: Configuración validada.
    :type settings: Settings
    :param request_id: Id de la petición en curso.
    :type request_id: str
    :param client: Nombre del cliente autenticado, o ``None``.
    :type client: str or None
    :return: Contexto de LangSmith, o uno nulo si el trazado está apagado.
    :rtype: ContextManager
    """
    if not is_enabled(settings):
        return contextlib.nullcontext()
    from langsmith import tracing_context  # pylint: disable=import-outside-toplevel

    return tracing_context(metadata={"request_id": request_id, "client": client})
