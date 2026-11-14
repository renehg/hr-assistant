"""Pruebas del enrutador por regla (``app/router.py``)."""

import pytest

from app.config import load_settings
from app.router import choose_route

LARGE_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


@pytest.mark.parametrize(
    ("question", "keyword"),
    [
        ("Compara Ventas y Finanzas", "compara"),
        ("RESUME el departamento de Ventas", "resume"),
        ("Explica quién lleva Finanzas", "explica"),
        ("¿Por qué EMP-0004 está en Ventas?", "por qué"),
        ("Analiza Tecnología", "analiza"),
        ("¿Quiénes son todos?", "todos"),
    ],
)
def test_each_keyword_sends_the_question_to_the_large_model(question, keyword):
    route = choose_route(question, load_settings({}))
    assert route.model == LARGE_MODEL
    assert route.reason == f"keyword:{keyword}"
