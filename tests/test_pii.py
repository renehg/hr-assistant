"""Pruebas de la detección y el enmascarado de PII (``app/pii.py``).

Contrato que fijan estas pruebas: ``detect(text)`` devuelve una lista de tipos
(``rfc``, ``curp``, ``email``, ``phone``) en ese orden fijo y sin repetidos;
``mask(text)`` reemplaza cada valor por ``[RFC]``, ``[CURP]``, ``[EMAIL]`` o
``[TELEFONO]``.
"""

from app.pii import detect, mask

RFC = "FLO010101AB1"
CURP = "GODE561231HDFRRN09"
EMAIL = "ana@ejemplo.com"
PHONE = "5512345678"


def test_detect_reports_types_in_fixed_order_without_repeats():
    text = f"tel {PHONE}, correo {EMAIL}, CURP {CURP}, RFC {RFC}, otra vez {EMAIL}"
    assert detect(text) == ["rfc", "curp", "email", "phone"]


def test_curp_alone_is_not_also_reported_as_rfc():
    assert detect(f"Mi CURP es {CURP}") == ["curp"]


def test_phone_glued_to_other_digits_is_not_reported():
    assert detect("Cuenta 123456789012 y folio 98765432101") == []


def test_mask_hides_every_value_behind_its_label():
    text = f"RFC {RFC}, CURP {CURP}, correo {EMAIL}, tel {PHONE}"
    assert mask(text) == "RFC [RFC], CURP [CURP], correo [EMAIL], tel [TELEFONO]"
