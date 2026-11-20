"""Pruebas de punta a punta de la sección «Factura» (spec/05-facturacion.md).

Se corren con pytest-playwright contra el producto vivo con el modelo simulado;
la URL base y la variable ``E2E_API_KEY`` las pone ``verification e2e``. La
clave nunca se escribe en la prueba.
"""

import os

from playwright.sync_api import Page, expect

KNOWN_CLIENT_TEXT = (
    "Fáctrale a Ferretería López 10 horas de consultoría fiscal "
    "y 2 paquetes de timbres"
)
EXPECTED_SUBTOTAL = "9200.00"
EXPECTED_VAT = "1472.00"
EXPECTED_TOTAL = "10672.00"
UNKNOWN_CLIENT_TEXT = "Factura a Cliente Fantasma 1 licencia mensual"
UNKNOWN_CLIENT_MESSAGE = "cliente no encontrado"


def _request_invoice(page: Page, text: str) -> None:
    """Abre la página con la clave válida y pide una factura.

    :param page: Página de Playwright.
    :type page: Page
    :param text: Frase en lenguaje natural que describe la factura.
    :type text: str
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(os.environ["E2E_API_KEY"])
    page.get_by_test_id("invoice-text").fill(text)
    page.get_by_test_id("invoice-send").click()


def test_an_invoice_phrase_shows_the_table_with_the_right_total(
    page: Page,
) -> None:
    """Una frase válida muestra el cliente, las líneas y los totales correctos."""
    _request_invoice(page, KNOWN_CLIENT_TEXT)

    result = page.get_by_test_id("invoice-result")
    expect(result).to_contain_text("Ferretería López")
    expect(result.locator("table")).to_be_visible()
    expect(result).to_contain_text(EXPECTED_SUBTOTAL)
    expect(result).to_contain_text(EXPECTED_VAT)
    expect(result).to_contain_text(EXPECTED_TOTAL)


def test_an_unknown_client_shows_the_error_message_in_spanish(
    page: Page,
) -> None:
    """Un cliente fuera del catálogo muestra el mensaje del servidor y ninguna tabla."""
    _request_invoice(page, UNKNOWN_CLIENT_TEXT)

    result = page.get_by_test_id("invoice-result")
    expect(result).to_contain_text(UNKNOWN_CLIENT_MESSAGE)
    expect(result.locator("table")).to_have_count(0)
