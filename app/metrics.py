"""Métricas en memoria de este proceso (cada copia reporta las suyas)."""

import math
import os
import threading
from collections import deque
from typing import Deque, Sequence

DEFAULT_LATENCY_WINDOW = 1000
SERVER_ERROR_STATUS = 500
DECIMALS = 3


def nearest_rank(sorted_values: Sequence[float], percentile: float) -> float:
    """Calcula un percentil por el método de rango más cercano.

    :param sorted_values: Valores ordenados de menor a mayor.
    :type sorted_values: Sequence[float]
    :param percentile: Percentil entre 0 y 100.
    :type percentile: float
    :return: El valor del percentil, o 0 si no hay valores.
    :rtype: float
    """
    if not sorted_values:
        return 0
    rank = max(1, math.ceil(percentile / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


class Metrics:  # pylint: disable=too-many-instance-attributes
    """Cuenta peticiones, errores, latencias, tokens y costo del proceso.

    Las latencias se guardan en una ventana acotada para que la memoria no
    crezca; los contadores cubren todas las peticiones.

    :param slo_p95_ms: Meta de latencia p95 en milisegundos.
    :type slo_p95_ms: int
    :param window: Cuántas latencias recientes se conservan.
    :type window: int
    """

    def __init__(self, slo_p95_ms: int, window: int = DEFAULT_LATENCY_WINDOW) -> None:
        if window < 1:
            raise ValueError("window must be at least 1")
        self._slo_p95_ms = slo_p95_ms
        self._latencies: Deque[float] = deque(maxlen=window)
        self._requests = 0
        self._errors = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd = 0.0
        self._lock = threading.Lock()

    def record_request(self, status: int, latency_ms: float) -> None:
        """Registra una petición terminada.

        :param status: Código HTTP de la respuesta; 5xx cuenta como error.
        :type status: int
        :param latency_ms: Latencia de la petición en milisegundos.
        :type latency_ms: float
        """
        with self._lock:
            self._requests += 1
            if status >= SERVER_ERROR_STATUS:
                self._errors += 1
            self._latencies.append(float(latency_ms))

    def record_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Suma los tokens de una corrida del agente.

        :param input_tokens: Tokens de entrada.
        :type input_tokens: int
        :param output_tokens: Tokens de salida.
        :type output_tokens: int
        """
        with self._lock:
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def record_cost(self, cost_usd: float) -> None:
        """Suma el costo de una corrida del agente, sin redondear.

        :param cost_usd: Costo en USD.
        :type cost_usd: float
        """
        with self._lock:
            self._cost_usd += cost_usd

    def snapshot(self) -> dict:
        """Arma el cuerpo de ``GET /metrics``.

        :return: ``pid``, ``requests``, ``error_rate``, ``latency_ms``,
            ``tokens``, ``cost_usd`` y ``slo``.
        :rtype: dict
        """
        with self._lock:
            latencies = sorted(self._latencies)
            requests = self._requests
            errors = self._errors
            tokens = {"input": self._input_tokens, "output": self._output_tokens}
            cost_usd = self._cost_usd
        p95 = round(nearest_rank(latencies, 95), DECIMALS)
        return {
            "pid": os.getpid(),
            "requests": requests,
            "error_rate": round(errors / requests, DECIMALS) if requests else 0,
            "latency_ms": {
                "p50": round(nearest_rank(latencies, 50), DECIMALS),
                "p95": p95,
            },
            "tokens": tokens,
            "cost_usd": cost_usd,
            "slo": {"p95_ms_target": self._slo_p95_ms, "met": p95 < self._slo_p95_ms},
        }
