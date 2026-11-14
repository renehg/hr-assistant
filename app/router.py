"""Enrutador por regla: elige el modelo de cada pregunta sin red ni estado."""

from dataclasses import dataclass

from app.config import Settings

LARGE_MODEL_KEYWORDS = ("compara", "resume", "explica", "por qué", "analiza", "todos")
REASON_ROUTING_DISABLED = "routing_disabled"
REASON_LONG_QUESTION = "long_question"
REASON_KEYWORD_PREFIX = "keyword:"
REASON_DEFAULT = "default"


@dataclass(frozen=True)
class Route:
    """Modelo elegido para una pregunta y el motivo.

    :param model: Nombre del modelo.
    :type model: str
    :param reason: Motivo: ``routing_disabled``, ``long_question``,
        ``keyword:<palabra>`` o ``default``.
    :type reason: str
    """

    model: str
    reason: str


def choose_route(question: str, settings: Settings) -> Route:
    """Elige el modelo de la pregunta con una regla fija.

    Va al modelo capaz si el enrutamiento está apagado, si la pregunta pasa de
    ``ROUTER_MAX_CHARS`` caracteres o si contiene una palabra clave (sin
    distinguir mayúsculas). Si no, va al modelo barato.

    :param question: Pregunta de la persona.
    :type question: str
    :param settings: Configuración validada.
    :type settings: Settings
    :return: Modelo y motivo.
    :rtype: Route
    """
    if not settings.routing:
        return Route(settings.model_large, REASON_ROUTING_DISABLED)
    if len(question) > settings.router_max_chars:
        return Route(settings.model_large, REASON_LONG_QUESTION)
    folded = question.casefold()
    for keyword in LARGE_MODEL_KEYWORDS:
        if keyword in folded:
            return Route(settings.model_large, REASON_KEYWORD_PREFIX + keyword)
    return Route(settings.model_small, REASON_DEFAULT)
