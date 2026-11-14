"""Pruebas del directorio de empleados de solo lectura."""


def test_employee_is_found_by_id(directory):
    employee = directory.get_employee("EMP-0004")
    assert employee["name"] == "Jorge Díaz"
    assert directory.get_employee("EMP-9999") is None


def test_department_search_ignores_case(directory):
    names = {employee["name"] for employee in directory.search_by_department("ventas")}
    assert names == {"Luis Pérez"}


def test_unknown_department_returns_no_employees(directory):
    assert directory.search_by_department("Marketing") == []
    assert set(directory.departments()) == {"Tecnología", "Ventas", "Finanzas"}
