"""Modelo real: Cloudflare Workers AI a través de AI Gateway, con ``httpx``.

El cliente HTTP se inyecta: las pruebas usan ``httpx.MockTransport`` y nunca
salen a la red. Cualquier fallo se convierte en ``ModelUnavailableError`` con un
mensaje que no incluye el token ni la URL de la cuenta.
"""

import json
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import httpx

from app.completion import Completion
from app.config import Settings

GATEWAY_URL_TEMPLATE = (
    "https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/"
    "workers-ai/v1/chat/completions"
)
DEFAULT_TIMEOUT_SECONDS = 30.0
CACHE_TTL_HEADER = "cf-aig-cache-ttl"
CACHE_STATUS_HEADER = "cf-aig-cache-status"
CACHE_HIT = "HIT"
SYSTEM_ROLE = "system"
PROTOCOL_PROMPT = (
    "Eres el asistente de Recursos Humanos. Responde siempre con un único objeto "
    "JSON y nada más. Para consultar el directorio pide una herramienta: "
    '{"tool": "get_employee", "args": {"employee_id": "EMP-0001"}} o '
    '{"tool": "search_by_department", "args": {"department": "Ventas"}}. '
    "Cuando tengas la respuesta final escribe "
    '{"answer": "respuesta breve en español"}. '
    "Usa solo los datos que devuelvan las herramientas; no inventes datos."
)


class ModelUnavailableError(RuntimeError):
    """El modelo real no respondió o su respuesta no se pudo interpretar."""


def _is_token_count(value: object) -> bool:
    """Indica si el valor es un conteo de tokens válido (entero de 0 o más).

    :param value: Valor leído de ``usage``.
    :type value: object
    :return: ``True`` si es un entero no negativo.
    :rtype: bool
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _content_text(content: object) -> str:
    """Convierte el contenido del mensaje del modelo en texto.

    Algunos modelos de Workers AI devuelven el JSON ya interpretado; en ese caso
    se vuelve a serializar para que el agente lo lea con su protocolo.

    :param content: ``choices[0].message.content``.
    :type content: object
    :return: El contenido como texto.
    :rtype: str
    :raises ModelUnavailableError: Si el contenido no es texto ni JSON.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False)
    raise ModelUnavailableError("gateway answer content is not text")


def _parse_body(body: object) -> Tuple[str, int, int]:
    """Lee el texto y los tokens de la respuesta compatible con OpenAI.

    :param body: Cuerpo JSON de la respuesta.
    :type body: object
    :return: Texto, tokens de entrada y tokens de salida.
    :rtype: tuple[str, int, int]
    :raises ModelUnavailableError: Si falta algún campo o no es válido.
    """
    try:
        content = body["choices"][0]["message"]["content"]  # type: ignore[index]
        usage = body["usage"]  # type: ignore[index]
        input_tokens = usage["prompt_tokens"]
        output_tokens = usage["completion_tokens"]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelUnavailableError("gateway answer has an invalid format") from error
    if not (_is_token_count(input_tokens) and _is_token_count(output_tokens)):
        raise ModelUnavailableError("gateway answer has an invalid usage")
    return _content_text(content), input_tokens, output_tokens


class GatewayModel:  # pylint: disable=too-few-public-methods
    """Modelo de Workers AI servido por AI Gateway.

    :param settings: Configuración validada (cuenta, gateway, token y palancas).
    :type settings: Settings
    :param model: Nombre del modelo, por ejemplo ``MODEL_SMALL``.
    :type model: str
    :param client: Cliente HTTP; si es ``None`` se crea uno con timeout.
    :type client: httpx.Client or None
    :param timeout_seconds: Tiempo máximo de cada llamada.
    :type timeout_seconds: float
    """

    def __init__(
        self,
        settings: Settings,
        model: str,
        client: Optional[httpx.Client] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.name = model
        self._settings = settings
        self._timeout = timeout_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._url = GATEWAY_URL_TEMPLATE.format(
            account_id=settings.cf_account_id, gateway_id=settings.cf_gateway_id
        )

    def complete(self, messages: Sequence[Mapping[str, str]]) -> Completion:
        """Llama al gateway con el prompt del protocolo y las palancas de costo.

        :param messages: Mensajes con ``role`` y ``content``.
        :type messages: Sequence[Mapping[str, str]]
        :return: Texto, tokens según ``usage`` y si salió de la caché.
        :rtype: Completion
        :raises ModelUnavailableError: Si falla la red, el tiempo, el status o
            el formato de la respuesta.
        """
        try:
            response = self._client.post(
                self._url,
                json=self._payload(messages),
                headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.HTTPError as error:
            raise ModelUnavailableError(
                f"gateway request failed: {type(error).__name__}"
            ) from None
        if not response.is_success:
            raise ModelUnavailableError(
                f"gateway answered with status {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError:
            raise ModelUnavailableError("gateway answer is not valid JSON") from None
        text, input_tokens, output_tokens = _parse_body(body)
        cached = response.headers.get(CACHE_STATUS_HEADER, "").upper() == CACHE_HIT
        return Completion(text, input_tokens, output_tokens, cached=cached)

    def _payload(self, messages: Sequence[Mapping[str, str]]) -> dict:
        """Arma el cuerpo con el prompt del protocolo antes de la conversación.

        Si la conversación ya empieza con un mensaje de sistema (el agente de
        facturación trae el suyo), se usa ese y no se agrega el de RH. La API
        nunca acepta mensajes de sistema de la persona (``HistoryMessage``).

        :param messages: Mensajes con ``role`` y ``content``.
        :type messages: Sequence[Mapping[str, str]]
        :return: ``model``, ``messages``, ``max_tokens`` y ``temperature``.
        :rtype: dict
        """
        conversation: List[Dict[str, str]] = []
        if not messages or str(messages[0]["role"]) != SYSTEM_ROLE:
            conversation.append({"role": SYSTEM_ROLE, "content": PROTOCOL_PROMPT})
        conversation.extend(
            {"role": str(item["role"]), "content": str(item["content"])}
            for item in messages
        )
        return {
            "model": self.name,
            "messages": conversation,
            "max_tokens": self._settings.model_max_tokens,
            "temperature": self._settings.model_temperature,
        }

    def _headers(self) -> Dict[str, str]:
        """Arma los encabezados: el token y, si aplica, el TTL de la caché.

        :return: Encabezados de la llamada.
        :rtype: dict[str, str]
        """
        headers = {"Authorization": f"Bearer {self._settings.cf_api_token}"}
        if self._settings.cache_ttl_seconds > 0:
            headers[CACHE_TTL_HEADER] = str(self._settings.cache_ttl_seconds)
        return headers
