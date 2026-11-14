# 0011. Límite de peticiones en memoria, por cliente y con reloj inyectado

Estado: propuesto. Matiza el ADR 0001 (API sin estado), igual que el ADR 0005 con las métricas.

## Contexto

Un cliente con una clave válida podría agotar la cuota del modelo. Hace falta un límite por cliente
que se pruebe sin esperar minutos reales y sin agregar infraestructura (Redis u otra base).

## Decisión

`app/rate_limit.py` implementa `RateLimiter` con ventana deslizante de 60 segundos: por cada
cliente guarda como máximo `RATE_LIMIT_PER_MINUTE` marcas del reloj monotónico inyectado. Si el
cliente ya las llenó, responde `429 {"detail": "rate limit exceeded"}` con `Retry-After` igual a los
segundos que faltan para que salga la marca más vieja, redondeados hacia arriba y mínimo 1. Se
revisa después de autenticar, así que solo se guardan clientes conocidos. `create_app` lo recibe
inyectado; las pruebas le dan su propio reloj.

## Consecuencias

- El estado vive en el proceso: no se comparte entre copias ni sobrevive a un reinicio. Con N copias
  el límite real es N veces el configurado. Se acepta con el plan free de Render (una copia).
- Si se escala horizontalmente, el límite se mueve a un almacén compartido sin cambiar la interfaz
  `check(client)`.
- La memoria está acotada: clientes de `API_KEYS` por `RATE_LIMIT_PER_MINUTE` marcas.
- `401` y `429` no cuentan en `error_rate`, que solo mide 5xx.
