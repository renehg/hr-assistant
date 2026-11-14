"""Prueba de humo contra el HR Assistant publicado (spec/04-production.md, punto 8).

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com``

La clave se lee de la variable ``SMOKE_API_KEY`` y nunca de un argumento, porque
quedaría en el historial de la terminal. La clave nunca se imprime.
"""

import os
import sys

import httpx

KEY_VARIABLE = "SMOKE_API_KEY"
QUESTION = {"question": "¿Quién es EMP-0004?"}
# Render despierta un servicio dormido en hasta un minuto
TIMEOUT_SECONDS = 90


def run_checks(url: str, key: str, client: httpx.Client) -> bool:
    """Comprueba ``/health``, ``/ask`` sin clave y ``/ask`` con clave.

    Imprime ``[OK]`` o ``[FAIL]`` con el código recibido en cada una: con él se
    ve la causa de una falla (401: la clave no coincide; 502: el modelo no
    responde).

    :param url: URL base del servicio, sin barra final.
    :type url: str
    :param key: Clave de un cliente de ``API_KEYS``.
    :type key: str
    :param client: Cliente HTTP a usar.
    :type client: httpx.Client
    :return: ``True`` si las tres comprobaciones pasan.
    :rtype: bool
    """
    checks = [
        ("GET /health", 200, lambda: client.get(f"{url}/health")),
        ("POST /ask sin clave", 401, lambda: client.post(f"{url}/ask", json=QUESTION)),
        ("POST /ask con clave", 200, lambda: client.post(
            f"{url}/ask", json=QUESTION, headers={"X-API-Key": key}
        )),
    ]
    passed = True
    for name, expected, send in checks:
        try:
            status = send().status_code
        except httpx.HTTPError as error:
            status = None
            detail = type(error).__name__
        else:
            detail = str(status)
        ok = status == expected
        passed = passed and ok
        print(f"[{'OK' if ok else 'FAIL'}] {name} -> {detail} (esperado {expected})")
    return passed


def main(args: list[str]) -> int:
    """Corre la prueba de humo; devuelve 0 si todo pasa.

    :param args: Argumentos de la línea de comandos sin el nombre del programa.
    :type args: list[str]
    :return: 0 si pasa, 1 si falla alguna comprobación, 2 si el uso es incorrecto.
    :rtype: int
    """
    key = os.environ.get(KEY_VARIABLE, "").strip()
    if len(args) != 1 or not key:
        print(f"Uso: {KEY_VARIABLE}=<clave> python scripts/smoke.py <url>")
        return 2
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        passed = run_checks(args[0].rstrip("/"), key, client)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
