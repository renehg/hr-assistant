"""Log estructurado: una línea JSON por evento en la salida estándar."""

import json
import sys
import threading
from datetime import timezone
from typing import Any, Optional, TextIO

from app.clock import Clock


class JsonLogger:
    """Escribe eventos como líneas JSON con ``ts``, ``service``, ``event``.

    Cada línea lleva además ``request_id`` y los campos propios del evento. Los
    valores se serializan con ``json.dumps``, así que ningún valor puede partir
    la línea ni inyectar otro evento.

    :param service: Nombre del servicio (campo ``service``).
    :type service: str
    :param clock: Reloj del que sale el campo ``ts``.
    :type clock: Clock
    :param stream: Flujo de salida; por omisión la salida estándar.
    :type stream: TextIO or None
    """

    def __init__(
        self, service: str, clock: Clock, stream: Optional[TextIO] = None
    ) -> None:
        self._service = service
        self._clock = clock
        self._stream = stream
        self._lock = threading.Lock()

    def emit(self, event: str, request_id: Optional[str], **fields: Any) -> None:
        """Escribe un evento en una sola línea JSON.

        Los campos obligatorios no se pueden sobrescribir con ``fields``.

        :param event: Nombre del evento (``request``, ``agent_run``...).
        :type event: str
        :param request_id: Id de la petición a la que pertenece el evento.
        :type request_id: str or None
        :param fields: Campos propios del evento.
        :type fields: Any
        """
        record = {
            "ts": self._timestamp(),
            "service": self._service,
            "event": event,
            "request_id": request_id,
        }
        for name, value in fields.items():
            record.setdefault(name, value)
        line = json.dumps(record, ensure_ascii=False, default=str)
        stream = self._stream if self._stream is not None else sys.stdout
        with self._lock:
            stream.write(line + "\n")
            stream.flush()

    def _timestamp(self) -> str:
        """Devuelve la hora del reloj en ISO 8601, en UTC y con sufijo ``Z``.

        :return: Marca de tiempo, por ejemplo ``2026-01-15T12:30:00.000Z``.
        :rtype: str
        """
        moment = self._clock.now().astimezone(timezone.utc)
        return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
