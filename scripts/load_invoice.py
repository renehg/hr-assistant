"""Prueba de carga concurrente contra ``POST /invoice``.

Uso::

    set LOAD_API_KEY=<clave completa>   (PowerShell: $env:LOAD_API_KEY = "...")
    python scripts/load_invoice.py https://mi-servicio.onrender.com

Manda ``--requests`` peticiones con ``--workers`` hilos en paralelo, repartidas
entre frases de factura correctas y rechazos esperados (422). Una petición
cuenta como buena si el estado y el total coinciden con lo esperado. Imprime
el resumen y sale con 1 si hubo algun 5xx o alguna respuesta inesperada.
La clave se lee del entorno; nunca se imprime.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CASES = [
    ("Factura a Panadería El Trigal: 1 licencia mensual de software",
     200, "1740.00"),
    ("Cobra a Clínica Dental Sonrisa 4 horas de soporte técnico",
     200, "2784.00"),
    ("Factura a Ferretería López 2 horas de consultoría fiscal",
     200, "1972.00"),
    ("Factura a Abarrotes La Esperanza 1 integración con ERP",
     200, "13920.00"),
    ("Factura a Transportes del Norte 3 sesiones de capacitación",
     200, "8700.00"),
    ("Factura a Panadería El Trigal 1 mantenimiento mensual",
     200, "2088.00"),
    ("Factura a Cliente Fantasma 1 licencia mensual",
     422, "cliente no encontrado"),
]


def percentile(values, fraction):
    """Devuelve el percentil (rango más cercano) de una lista de números."""
    ordered = sorted(values)
    index = max(0, int(round(fraction * len(ordered))) - 1)
    return ordered[index]


def fetch(request):
    """Envía la petición; devuelve ``(estado, cuerpo)`` (estado 0 si falla)."""
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8") or "{}"
        return error.code, json.loads(raw)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return 0, {}


def call(url, key, case):
    """Devuelve ``(estado, ok, segundos, costo, encontrado)`` de una frase."""
    text, want_status, want = case
    request = urllib.request.Request(
        url + "/invoice",
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"X-API-Key": key,
                 "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.perf_counter()
    status, body = fetch(request)
    elapsed = time.perf_counter() - started
    if status == 200:
        found = body.get("invoice", {}).get("total")
        good = want_status == 200 and found == want
        cost = float(body.get("cost_usd", 0.0))
        return status, good, elapsed, cost, found
    found = str(body.get("detail", ""))
    good = status == want_status and want in found
    return status, good, elapsed, 0.0, found


def main():
    """Corre la prueba y muestra el resumen."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("url", help="URL base del servicio, sin /invoice")
    parser.add_argument("--requests", type=int, default=25)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    key = os.environ.get("LOAD_API_KEY", "")
    if not key:
        print("Falta LOAD_API_KEY en el entorno.", file=sys.stderr)
        return 2
    url = args.url.rstrip("/")
    cases = [CASES[i % len(CASES)] for i in range(args.requests)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda c: call(url, key, c), cases))
    code = summarize(results, time.perf_counter() - started, args.workers)
    breakdown(cases, results)
    return code


def summarize(results, total_time, workers):
    """Imprime el resumen y devuelve el código de salida."""
    times = [r[2] for r in results]
    good = sum(1 for r in results if r[1])
    errors_5xx = sum(1 for r in results if r[0] >= 500)
    no_answer = sum(1 for r in results if r[0] == 0)
    print(f"peticiones: {len(results)} con {workers} en paralelo")
    print(f"correctas (estado y total esperados): {good}")
    print(f"errores 5xx: {errors_5xx}, sin respuesta: {no_answer}")
    print(f"p50: {percentile(times, 0.5) * 1000:.0f} ms, "
          f"p95: {percentile(times, 0.95) * 1000:.0f} ms, "
          f"max: {max(times) * 1000:.0f} ms")
    print(f"rendimiento: {len(results) / total_time:.1f} peticiones/s")
    print(f"costo total: {sum(r[3] for r in results):.6f} USD")
    return 0 if good == len(results) and not errors_5xx else 1


def breakdown(cases, results):
    """Imprime, por frase, cuántas salieron bien y qué se recibió si no."""
    print("\ndetalle por frase (esperado -> recibido cuando falla):")
    for case in CASES:
        mine = [r for c, r in zip(cases, results) if c == case]
        good = sum(1 for r in mine if r[1])
        print(f"  {good}/{len(mine)}  {case[0]}")
        for status, ok, _, _, found in mine:
            if not ok:
                print(f"       esperaba {case[1]} {case[2]!r}, "
                      f"recibió {status} {found!r}")
                break


if __name__ == "__main__":
    sys.exit(main())
