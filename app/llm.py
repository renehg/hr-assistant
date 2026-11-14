"""Interfaz del modelo de lenguaje, modelo simulado y fábrica de modelos."""

import json
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import httpx

from app.completion import Completion, LanguageModel
from app.config import PROVIDER_FAKE, PROVIDER_GATEWAY, Settings
from app.directory import EmployeeDirectory
from app.gateway import GatewayModel

__all__ = [
    "Completion",
    "FakeModel",
    "LanguageModel",
    "build_models",
    "HELP_MESSAGE",
    "TOOL_RESULT_PREFIX",
]

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
HELP_MESSAGE = "Pregúntame por un empleado (EMP-0001) o un departamento."
EMPLOYEE_ID_PATTERN = re.compile(r"EMP-\d{4}")
DEFAULT_FAKE_NAME = "fake"


def _count_words(texts: Iterable[str]) -> int:
    """Cuenta palabras separadas por espacios.

    :param texts: Textos a contar.
    :type texts: Iterable[str]
    :return: Total de palabras.
    :rtype: int
    """
    return sum(len(str(text).split()) for text in texts)


class FakeModel:  # pylint: disable=too-few-public-methods
    """Modelo simulado, determinista y sin red.

    El nombre solo sirve para calcular el costo con el precio de ese modelo:
    dos simulados con distinto nombre responden exactamente igual.

    :param departments: Departamentos que existen en los datos.
    :type departments: Iterable[str]
    :param name: Nombre con el que se cobra, por ejemplo ``MODEL_SMALL``.
    :type name: str
    """

    def __init__(
        self, departments: Iterable[str], name: str = DEFAULT_FAKE_NAME
    ) -> None:
        self._departments = tuple(departments)
        self.name = name

    def complete(self, messages: Sequence[Mapping[str, str]]) -> Completion:
        """Decide la respuesta con las reglas del spec sobre el último mensaje.

        :param messages: Mensajes con ``role`` y ``content``.
        :type messages: Sequence[Mapping[str, str]]
        :return: Un objeto JSON con ``tool``/``args`` o con ``answer``.
        :rtype: Completion
        """
        last = str(messages[-1]["content"]) if messages else ""
        text = json.dumps(self._decide(last), ensure_ascii=False)
        return Completion(
            text=text,
            input_tokens=_count_words(m["content"] for m in messages),
            output_tokens=_count_words([text]),
        )

    def _decide(self, last: str) -> dict:
        """Aplica las cuatro reglas en orden de prioridad.

        :param last: Contenido del último mensaje.
        :type last: str
        :return: Respuesta del protocolo.
        :rtype: dict
        """
        if last.startswith(TOOL_RESULT_PREFIX):
            result = last[len(TOOL_RESULT_PREFIX):]
            return {"answer": "Según el directorio: " + result}
        match = EMPLOYEE_ID_PATTERN.search(last)
        if match:
            return {"tool": "get_employee", "args": {"employee_id": match.group(0)}}
        department = self._find_department(last)
        if department is not None:
            return {
                "tool": "search_by_department",
                "args": {"department": department},
            }
        return {"answer": HELP_MESSAGE}

    def _find_department(self, text: str) -> Optional[str]:
        """Busca un departamento mencionado en el texto, sin distinguir mayúsculas.

        :param text: Texto a revisar.
        :type text: str
        :return: Nombre del departamento o ``None``.
        :rtype: str or None
        """
        folded = text.casefold()
        for department in self._departments:
            if department.casefold() in folded:
                return department
        return None


def build_models(
    settings: Settings,
    directory: EmployeeDirectory,
    client: Optional[httpx.Client] = None,
) -> Dict[str, LanguageModel]:
    """Crea los dos modelos (``MODEL_SMALL`` y ``MODEL_LARGE``) del proveedor.

    :param settings: Configuración validada.
    :type settings: Settings
    :param directory: Directorio de empleados (para conocer los departamentos).
    :type directory: EmployeeDirectory
    :param client: Cliente HTTP del gateway; ``None`` crea uno con timeout.
    :type client: httpx.Client or None
    :return: Un modelo por nombre.
    :rtype: dict[str, LanguageModel]
    :raises ValueError: Si el proveedor no está soportado.
    """
    names = (settings.model_small, settings.model_large)
    if settings.model_provider == PROVIDER_FAKE:
        departments: List[str] = directory.departments()
        return {name: FakeModel(departments, name=name) for name in names}
    if settings.model_provider == PROVIDER_GATEWAY:
        shared = client or httpx.Client()
        return {
            name: GatewayModel(settings=settings, model=name, client=shared)
            for name in names
        }
    raise ValueError(f"MODEL_PROVIDER not supported: {settings.model_provider!r}")
