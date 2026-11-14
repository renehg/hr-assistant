"""Tipos comunes a todos los modelos: la respuesta y la interfaz ``complete``.

Viven aparte para que ``llm`` y ``gateway`` los compartan sin importarse entre sí.
"""

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Completion:
    """Respuesta de un modelo.

    :param text: Texto devuelto (un objeto JSON).
    :type text: str
    :param input_tokens: Tokens de entrada consumidos.
    :type input_tokens: int
    :param output_tokens: Tokens de salida producidos.
    :type output_tokens: int
    :param cached: Si la respuesta salió de la caché del gateway (no cuesta).
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    cached: bool = False


class LanguageModel(Protocol):  # pylint: disable=too-few-public-methods
    """Interfaz que debe cumplir cualquier modelo usado por el agente."""

    def complete(self, messages: Sequence[Mapping[str, str]]) -> Completion:
        """Completa una conversación.

        :param messages: Mensajes con ``role`` y ``content``.
        :type messages: Sequence[Mapping[str, str]]
        :return: La respuesta del modelo.
        :rtype: Completion
        """
