"""Pruebas de la tabla de precios (``app/pricing.py``)."""

import pytest

from app.config import load_settings
from app.pricing import PriceTable

SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


@pytest.fixture
def prices():
    """Precios leídos de ``data/model_prices.json``."""
    return PriceTable.from_file(load_settings({}).prices_path)


def test_cost_is_priced_per_million_tokens(prices):
    cost = prices.cost_usd(LARGE_MODEL, input_tokens=1_000_000, output_tokens=500_000)
    assert cost == pytest.approx(0.293 + 2.253 / 2)


def test_a_tiny_cost_is_not_rounded_to_zero(prices):
    cost = prices.cost_usd(SMALL_MODEL, input_tokens=1, output_tokens=0)
    assert cost == pytest.approx(0.045 / 1_000_000)
    assert cost > 0


def test_a_model_without_price_is_an_error(prices):
    with pytest.raises(ValueError, match="gpt-unknown"):
        prices.cost_usd("gpt-unknown", input_tokens=10, output_tokens=10)
