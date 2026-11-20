"""Pruebas del catálogo cerrado (``app/catalog.py``).

Cubren la normalización, la búsqueda de alias (el más largo gana, sin
traslapes, con límites de palabra) y que un catálogo inválido no cargue.
"""

import json
from pathlib import Path

import pytest

from app.catalog import Catalog, find_mentions, normalize
from app.config import load_settings


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ferretería LÓPEZ", "ferreteria lopez"),
        ("Señor  Muñoz", "senor munoz"),
        ("  Clínica   Dental  ", "clinica dental"),
    ],
)
def test_normalize_removes_accents_capitals_and_extra_spaces(text, expected):
    assert normalize(text) == expected


def test_longest_alias_wins_and_mentions_do_not_overlap(catalog):
    text = "Soporte técnico y Licencia mensual de software"

    mentions = find_mentions(text, catalog.concepts)

    assert [m.alias for m in mentions] == [
        "soporte tecnico",
        "licencia mensual de software",
    ]
    assert [m.entry.id for m in mentions] == ["CON-002", "CON-003"]


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("3 licencia", ["CON-003"]),
        ("3 licencias", []),
        ("supersoporte", []),
        ("soporte, por favor", ["CON-002"]),
    ],
)
def test_aliases_only_match_whole_words(catalog, text, found):
    assert [m.entry.id for m in find_mentions(text, catalog.concepts)] == found


def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _real_entries(name):
    settings = load_settings({})
    source = settings.clientes_path if name == "clientes" else settings.conceptos_path
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _repeated_id(entries):
    entries[1]["id"] = entries[0]["id"]


def _bad_rfc(entries):
    entries[0]["rfc"] = "NO-ES-RFC"


def _price_without_cents(entries):
    entries[0]["precio_unitario"] = "850"


def _zero_price(entries):
    entries[0]["precio_unitario"] = "0.00"


def _empty_alias(entries):
    entries[0]["aliases"] = ["   "]


@pytest.mark.parametrize(
    ("name", "spoil"),
    [
        ("clientes", _repeated_id),
        ("clientes", _bad_rfc),
        ("clientes", _empty_alias),
        ("conceptos", _repeated_id),
        ("conceptos", _price_without_cents),
        ("conceptos", _zero_price),
    ],
    ids=[
        "repeated_client_id",
        "bad_rfc",
        "empty_alias",
        "repeated_concept_id",
        "price_without_cents",
        "zero_price",
    ],
)
def test_invalid_catalog_does_not_load(tmp_path, name, spoil):
    files = {key: _real_entries(key) for key in ("clientes", "conceptos")}
    spoil(files[name])
    clientes = _write(tmp_path / "clientes.json", files["clientes"])
    conceptos = _write(tmp_path / "conceptos.json", files["conceptos"])

    with pytest.raises(ValueError) as raised:
        Catalog.from_files(clientes, conceptos)

    assert "FLO010101AB1" not in str(raised.value)


def test_real_catalog_resolves_clients_and_concepts_by_id_and_alias(catalog):
    assert catalog.find_client("Factura a FERRETERÍA López").id == "CLI-001"
    assert catalog.find_client("Cliente Desconocido") is None
    assert catalog.client_by_id("CLI-999") is None
    assert catalog.concept_by_id("CON-004").precio_unitario == 350
