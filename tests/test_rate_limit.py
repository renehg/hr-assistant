"""Pruebas del límite de peticiones por cliente (``app/rate_limit.py``).

Contrato que fijan estas pruebas: ``RateLimiter(limit_per_minute, clock)`` usa
una ventana deslizante de 60 segundos por cliente. ``check(client)`` devuelve
``None`` si la petición pasa, o los segundos enteros de ``Retry-After``
(redondeados hacia arriba, mínimo 1) si no pasa. Una petición rechazada no
cuenta dentro de la ventana.
"""

from app.rate_limit import RateLimiter


def test_requests_up_to_the_limit_pass_and_the_next_one_waits_a_minute(
    manual_clock,
):
    limiter = RateLimiter(limit_per_minute=2, clock=manual_clock)
    assert limiter.check("acme") is None
    assert limiter.check("acme") is None
    assert limiter.check("acme") == 60


def test_retry_after_is_rounded_up_to_whole_seconds(manual_clock):
    limiter = RateLimiter(limit_per_minute=1, clock=manual_clock)
    assert limiter.check("acme") is None
    manual_clock.advance(0.5)
    assert limiter.check("acme") == 60
    manual_clock.advance(59.4)
    assert limiter.check("acme") == 1


def test_rejected_requests_do_not_extend_the_wait(manual_clock):
    limiter = RateLimiter(limit_per_minute=1, clock=manual_clock)
    assert limiter.check("acme") is None
    manual_clock.advance(30)
    assert limiter.check("acme") == 30
    manual_clock.advance(30.5)
    assert limiter.check("acme") is None
