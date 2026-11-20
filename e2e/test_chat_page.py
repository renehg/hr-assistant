"""Pruebas de punta a punta de la página del HR Assistant (spec/04-production.md).

Se corren con pytest-playwright contra el producto vivo con el modelo simulado;
la URL base y la variable ``E2E_API_KEY`` las pone ``verification e2e``. La
clave nunca se escribe en la prueba.
"""

import os
import re

from playwright.sync_api import Page, expect

FIRST_QUESTION = "Dame los datos de EMP-0001"
SECOND_QUESTION = "Hola, ¿qué puedes hacer?"
REQUEST_ID_PATTERN = re.compile(r"request_id\)?:\s*\S+")
INVALID_KEY_MESSAGE = "Clave inválida"


def _valid_api_key() -> str:
    """Devuelve la clave válida que pone la verificación.

    :return: Clave leída de la variable de entorno ``E2E_API_KEY``.
    :rtype: str
    """
    return os.environ["E2E_API_KEY"]


def _open_with_key(page: Page, api_key: str) -> None:
    """Abre la página y escribe la clave en su campo.

    :param page: Página de Playwright.
    :type page: Page
    :param api_key: Clave que se escribe en el campo ``api-key``.
    :type api_key: str
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(api_key)


def _ask(page: Page, question: str) -> None:
    """Escribe una pregunta en la caja y la envía con el botón.

    :param page: Página de Playwright ya abierta en el producto.
    :type page: Page
    :param question: Texto de la pregunta.
    :type question: str
    """
    page.get_by_test_id("question").fill(question)
    page.get_by_test_id("send").click()


def test_asking_a_question_shows_the_answer_and_its_request_id(page: Page) -> None:
    """Con la clave válida (en un campo oculto), una pregunta muestra la respuesta.

    También comprueba que el campo de clave es de tipo contraseña.
    """
    _open_with_key(page, _valid_api_key())
    expect(page.get_by_test_id("api-key")).to_have_attribute("type", "password")
    _ask(page, FIRST_QUESTION)

    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(FIRST_QUESTION)
    expect(answer).to_contain_text("Asistente:")
    request_id = page.get_by_test_id("request_id")
    expect(request_id).to_have_count(1)
    expect(request_id).to_have_text(REQUEST_ID_PATTERN)


def test_an_empty_question_shows_an_error_message_in_spanish(page: Page) -> None:
    """Enviar la caja vacía muestra un error en español y no consulta a la API."""
    _open_with_key(page, _valid_api_key())
    _ask(page, "   ")

    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text("Escribe una pregunta")
    expect(page.get_by_test_id("request_id")).to_have_count(0)


def test_a_second_question_keeps_the_previous_conversation_on_screen(
    page: Page,
) -> None:
    """La segunda pregunta se agrega sin borrar la primera ni su respuesta."""
    _open_with_key(page, _valid_api_key())
    _ask(page, FIRST_QUESTION)
    expect(page.get_by_test_id("request_id")).to_have_count(1)

    _ask(page, SECOND_QUESTION)

    answer = page.get_by_test_id("answer")
    expect(page.get_by_test_id("request_id")).to_have_count(2)
    expect(answer).to_contain_text(FIRST_QUESTION)
    expect(answer).to_contain_text(SECOND_QUESTION)
    expect(answer).to_have_text(re.compile(r"Asistente:.*Asistente:", re.DOTALL))


def test_a_wrong_api_key_shows_invalid_key_message(page: Page) -> None:
    """Una clave equivocada muestra «Clave inválida» y ninguna respuesta."""
    _open_with_key(page, _valid_api_key() + "-wrong")
    _ask(page, FIRST_QUESTION)

    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(INVALID_KEY_MESSAGE)
    expect(answer).not_to_contain_text("Asistente:")
