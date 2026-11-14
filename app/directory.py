"""Directorio de empleados de solo lectura cargado desde un archivo JSON."""

import copy
import json
from pathlib import Path
from typing import List, Optional


class EmployeeDirectory:
    """Directorio de empleados en memoria, de solo lectura.

    :param path: Ruta al archivo JSON con la lista de empleados.
    :type path: str
    """

    def __init__(self, path: str) -> None:
        with Path(path).open(encoding="utf-8") as handle:
            self._employees = tuple(json.load(handle))

    def get_employee(self, employee_id: str) -> Optional[dict]:
        """Busca un empleado por su id.

        :param employee_id: Id del empleado, por ejemplo ``EMP-0004``.
        :type employee_id: str
        :return: Copia de los datos del empleado o ``None`` si no existe.
        :rtype: dict or None
        """
        wanted = str(employee_id).strip().upper()
        for employee in self._employees:
            if employee["id"].upper() == wanted:
                return copy.deepcopy(employee)
        return None

    def search_by_department(self, department: str) -> List[dict]:
        """Lista los empleados de un departamento sin distinguir mayúsculas.

        :param department: Nombre del departamento.
        :type department: str
        :return: Copias de los empleados del departamento (puede estar vacía).
        :rtype: list[dict]
        """
        wanted = str(department).strip().casefold()
        return [
            copy.deepcopy(employee)
            for employee in self._employees
            if employee["department"].casefold() == wanted
        ]

    def departments(self) -> List[str]:
        """Devuelve los departamentos sin repetir, en orden de aparición.

        :return: Nombres de los departamentos.
        :rtype: list[str]
        """
        names: List[str] = []
        for employee in self._employees:
            if employee["department"] not in names:
                names.append(employee["department"])
        return names
