"""Pruebas de las claves por cliente (``app/security.py``).

Contrato que fijan estas pruebas:

- ``parse_api_keys(raw)`` recibe ``cliente:clave,cliente2:clave2`` y devuelve un
  diccionario ``{cliente: clave}``; los espacios a los lados se ignoran.
- Una entrada mal formada lanza ``ValueError`` con el número de la entrada
  (contando desde 1) y su largo, nunca su valor.
- ``ApiKeyAuthenticator(keys).client_for(key)`` devuelve el nombre del cliente o
  ``None`` si la clave falta o no coincide.
"""

import pytest

from app.security import ApiKeyAuthenticator, parse_api_keys


def test_api_keys_are_parsed_into_clients_and_their_keys():
    keys = parse_api_keys(" acme : key-one-123 , beta:key-two-456 ")
    assert dict(keys) == {"acme": "key-one-123", "beta": "key-two-456"}


@pytest.mark.parametrize(
    ("raw", "hidden_values"),
    [
        ("acme:key-one-123,beta:", ["beta"]),
        ("acme:key-one-123,acme:key-two-456", ["key-one-123", "key-two-456"]),
    ],
    ids=["empty key", "duplicated client"],
)
def test_malformed_entry_is_named_by_position_without_its_value(raw, hidden_values):
    with pytest.raises(ValueError) as raised:
        parse_api_keys(raw)
    message = str(raised.value)
    assert "2" in message
    for value in hidden_values:
        assert value not in message


def test_authenticator_finds_the_client_only_for_a_valid_key():
    authenticator = ApiKeyAuthenticator(
        {"acme": "key-one-123", "beta": "key-two-456"}
    )
    assert authenticator.client_for("key-two-456") == "beta"
    assert authenticator.client_for("key-two-45") is None
    assert authenticator.client_for("") is None
    assert authenticator.client_for(None) is None
