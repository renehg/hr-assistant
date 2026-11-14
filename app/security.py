"""Claves por cliente: lectura de ``API_KEYS`` y búsqueda del cliente por su clave.

Ninguna función de este módulo escribe una clave en un mensaje: los errores
nombran la variable, el número de la entrada y su largo. No importa
``app.config`` para evitar un ciclo de importación.
"""

import hmac
from typing import Dict, Mapping, Optional, Tuple

API_KEYS_VARIABLE = "API_KEYS"
ENTRY_SEPARATOR = ","
CLIENT_SEPARATOR = ":"
KEY_ENCODING = "utf-8"


def _entry_error(position: int, entry: str, reason: str) -> ValueError:
    """Arma el error de una entrada mal formada sin incluir su valor.

    :param position: Número de la entrada, contando desde 1.
    :type position: int
    :param entry: Texto de la entrada; solo se usa su largo.
    :type entry: str
    :param reason: Motivo del error, sin datos de la entrada.
    :type reason: str
    :return: El error listo para lanzar.
    :rtype: ValueError
    """
    return ValueError(
        f"{API_KEYS_VARIABLE} entry {position} (length {len(entry)}) is invalid: "
        f"{reason}; expected client:key"
    )


def _parse_entry(position: int, entry: str) -> Tuple[str, str]:
    """Separa una entrada ``cliente:clave``.

    :param position: Número de la entrada, contando desde 1.
    :type position: int
    :param entry: Entrada sin espacios a los lados.
    :type entry: str
    :return: El nombre del cliente y su clave.
    :rtype: tuple[str, str]
    :raises ValueError: Si falta ``:``, el cliente o la clave.
    """
    client, separator, key = entry.partition(CLIENT_SEPARATOR)
    if not separator:
        raise _entry_error(position, entry, "missing ':'")
    client, key = client.strip(), key.strip()
    if not client:
        raise _entry_error(position, entry, "empty client")
    if not key:
        raise _entry_error(position, entry, "empty key")
    return client, key


def parse_api_keys(raw: Optional[str]) -> Dict[str, str]:
    """Lee ``API_KEYS`` con la forma ``cliente:clave,cliente2:clave2``.

    Los espacios a los lados de cada parte se ignoran. Un texto vacío no define
    ningún cliente.

    :param raw: Valor de ``API_KEYS`` o ``None``.
    :type raw: str or None
    :return: Clave de cada cliente, por nombre de cliente.
    :rtype: dict[str, str]
    :raises ValueError: Si una entrada está mal formada o repite un cliente; el
        mensaje dice el número de la entrada y su largo, nunca su valor.
    """
    if raw is None or not raw.strip():
        return {}
    keys: Dict[str, str] = {}
    for position, part in enumerate(raw.split(ENTRY_SEPARATOR), start=1):
        entry = part.strip()
        client, key = _parse_entry(position, entry)
        if client in keys:
            raise _entry_error(position, entry, "duplicated client")
        keys[client] = key
    return keys


class ApiKeyAuthenticator:
    """Encuentra el cliente dueño de una clave con comparación de tiempo constante.

    La clave recibida se compara con ``hmac.compare_digest`` contra todas las
    claves, sin cortar al primer acierto, para no revelar nada por el tiempo.

    :param keys: Clave de cada cliente, por nombre de cliente.
    :type keys: Mapping[str, str]
    """

    def __init__(self, keys: Mapping[str, str]) -> None:
        self._entries = tuple(
            (client, key.encode(KEY_ENCODING)) for client, key in keys.items()
        )

    def client_for(self, key: Optional[str]) -> Optional[str]:
        """Devuelve el nombre del cliente dueño de la clave.

        :param key: Valor del encabezado ``X-API-Key`` o ``None``.
        :type key: str or None
        :return: El nombre del cliente, o ``None`` si falta o no coincide.
        :rtype: str or None
        """
        if not key:
            return None
        candidate = key.encode(KEY_ENCODING)
        found: Optional[str] = None
        for client, expected in self._entries:
            if hmac.compare_digest(candidate, expected):
                found = client
        return found
