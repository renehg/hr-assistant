"""Detección y enmascarado de datos personales (PII) sin guardar valores.

Tipos: ``rfc``, ``curp``, ``email`` y ``phone`` (10 dígitos sin otros dígitos
pegados). Se enmascara en este orden: correo, CURP, RFC y teléfono, porque una
CURP empieza con algo que tiene forma de RFC y un correo puede traer dígitos.
RFC y CURP se buscan sin distinguir mayúsculas, para no dejar pasar uno escrito
en minúsculas.
"""

import re
from typing import List, Pattern, Tuple

TYPE_RFC = "rfc"
TYPE_CURP = "curp"
TYPE_EMAIL = "email"
TYPE_PHONE = "phone"
REPORT_ORDER = (TYPE_RFC, TYPE_CURP, TYPE_EMAIL, TYPE_PHONE)

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CURP_PATTERN = re.compile(
    r"(?<![A-Z0-9])[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d(?![A-Z0-9])", re.IGNORECASE
)
RFC_PATTERN = re.compile(
    r"(?<![A-ZÑ&0-9])[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}(?![A-Z0-9])", re.IGNORECASE
)
PHONE_PATTERN = re.compile(r"(?<!\d)\d{10}(?!\d)")

MASK_ORDER: Tuple[Tuple[str, Pattern[str], str], ...] = (
    (TYPE_EMAIL, EMAIL_PATTERN, "[EMAIL]"),
    (TYPE_CURP, CURP_PATTERN, "[CURP]"),
    (TYPE_RFC, RFC_PATTERN, "[RFC]"),
    (TYPE_PHONE, PHONE_PATTERN, "[TELEFONO]"),
)

RFC_VISIBLE_CHARS = 3
RFC_HIDDEN_MARK = "*****"


def _scan(text: str) -> Tuple[str, List[str]]:
    """Enmascara el texto y anota qué tipos encontró.

    :param text: Texto a revisar.
    :type text: str
    :return: El texto enmascarado y los tipos encontrados, sin orden fijo.
    :rtype: tuple[str, list[str]]
    """
    found = []
    masked = text
    for kind, pattern, label in MASK_ORDER:
        masked, count = pattern.subn(label, masked)
        if count:
            found.append(kind)
    return masked, found


def detect(text: str) -> List[str]:
    """Devuelve los tipos de PII del texto, nunca sus valores.

    :param text: Texto a revisar.
    :type text: str
    :return: Tipos en orden fijo (``rfc``, ``curp``, ``email``, ``phone``) y
        sin repetidos; vacía si no hay PII.
    :rtype: list[str]
    """
    _, found = _scan(text)
    return [kind for kind in REPORT_ORDER if kind in found]


def mask(text: str) -> str:
    """Reemplaza cada valor de PII por su etiqueta.

    :param text: Texto a enmascarar.
    :type text: str
    :return: El texto con ``[RFC]``, ``[CURP]``, ``[EMAIL]`` o ``[TELEFONO]``.
    :rtype: str
    """
    masked, _ = _scan(text)
    return masked


def mask_rfc(rfc: str) -> str:
    """Deja ver solo el inicio y el final de un RFC (``FLO*****AB1``).

    :param rfc: RFC completo.
    :type rfc: str
    :return: El RFC parcial; un valor demasiado corto se oculta completo.
    :rtype: str
    """
    if len(rfc) <= 2 * RFC_VISIBLE_CHARS:
        return RFC_HIDDEN_MARK
    return rfc[:RFC_VISIBLE_CHARS] + RFC_HIDDEN_MARK + rfc[-RFC_VISIBLE_CHARS:]
