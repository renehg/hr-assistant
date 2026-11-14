"""Reloj inyectado: el único lugar del producto que lee la hora del sistema."""

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Interfaz de reloj que reciben el logger y la API."""

    def now(self) -> datetime:
        """Devuelve el momento actual con zona horaria UTC.

        :return: Momento actual en UTC.
        :rtype: datetime
        """

    def monotonic(self) -> float:
        """Devuelve segundos de un reloj que nunca retrocede.

        :return: Segundos desde un origen arbitrario.
        :rtype: float
        """


class SystemClock:
    """Reloj real del sistema."""

    def now(self) -> datetime:
        """Devuelve la hora actual en UTC.

        :return: Momento actual en UTC.
        :rtype: datetime
        """
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        """Devuelve el reloj monotónico del sistema, para medir latencias.

        :return: Segundos desde un origen arbitrario.
        :rtype: float
        """
        return time.monotonic()


class FixedClock:
    """Reloj de prueba que siempre devuelve el mismo momento.

    :param moment: Momento a devolver; si no trae zona se asume UTC.
    :type moment: datetime
    :param monotonic_value: Valor fijo del reloj monotónico.
    :type monotonic_value: float
    """

    def __init__(self, moment: datetime, monotonic_value: float = 0.0) -> None:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        self._moment = moment
        self._monotonic_value = monotonic_value

    def now(self) -> datetime:
        """Devuelve el momento fijo.

        :return: El momento recibido al construir el reloj.
        :rtype: datetime
        """
        return self._moment

    def monotonic(self) -> float:
        """Devuelve el valor monotónico fijo.

        :return: El valor recibido al construir el reloj.
        :rtype: float
        """
        return self._monotonic_value
