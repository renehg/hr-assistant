"""Límite de peticiones por cliente, en memoria del proceso, con reloj inyectado.

Cada copia del producto cuenta solo sus peticiones (ver ADR 0011).
"""

import math
import threading
from collections import deque
from typing import Deque, Dict, Optional

from app.clock import Clock

WINDOW_SECONDS = 60.0
MIN_RETRY_AFTER_SECONDS = 1


class RateLimiter:
    """Ventana deslizante de 60 segundos por cliente.

    Solo se guardan las marcas de tiempo de las peticiones que pasan, así que
    cada cliente ocupa como máximo ``limit_per_minute`` marcas y una petición
    rechazada no alarga la espera.

    :param limit_per_minute: Peticiones permitidas por cliente en la ventana.
    :type limit_per_minute: int
    :param clock: Reloj del que se lee ``monotonic()``.
    :type clock: Clock
    :raises ValueError: Si el límite es menor que 1.
    """

    def __init__(self, limit_per_minute: int, clock: Clock) -> None:
        if limit_per_minute < 1:
            raise ValueError("limit_per_minute must be at least 1")
        self._limit = limit_per_minute
        self._clock = clock
        self._windows: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, client: str) -> Optional[int]:
        """Registra una petición del cliente si cabe en la ventana.

        :param client: Nombre del cliente ya autenticado (nunca su clave).
        :type client: str
        :return: ``None`` si la petición pasa; si no, los segundos enteros de
            ``Retry-After``, redondeados hacia arriba y mínimo 1.
        :rtype: int or None
        """
        now = self._clock.monotonic()
        with self._lock:
            window = self._windows.setdefault(client, deque())
            while window and now - window[0] >= WINDOW_SECONDS:
                window.popleft()
            if len(window) < self._limit:
                window.append(now)
                return None
            remaining = window[0] + WINDOW_SECONDS - now
        return max(MIN_RETRY_AFTER_SECONDS, math.ceil(remaining))
