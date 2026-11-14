# 0009. Modelo real por AI Gateway con cliente HTTP inyectado

Estado: propuesto. Amplía el ADR 0002, que solo aceptaba `fake`.

## Contexto

El producto necesita un modelo real (Workers AI) con caché y registro de llamadas, sin que las
pruebas usen la red ni el token se filtre.

## Decisión

`app/gateway.py` implementa `complete(messages)` llamando al endpoint compatible con OpenAI de AI
Gateway con `httpx`. El `httpx.Client` se inyecta (las pruebas usan `MockTransport`) y tiene timeout
explícito. Agrega el prompt del protocolo JSON, `max_tokens`, `temperature` y, si el TTL es mayor que
0, `cf-aig-cache-ttl`. Cualquier fallo se convierte en `ModelUnavailableError`, que `/ask` responde
como `502 {"detail": "model unavailable", "request_id"}`. Con `MODEL_PROVIDER=gateway` faltar un
`CF_*` impide arrancar; el token no aparece en `repr`, logs ni errores.

## Consecuencias

- `agent.py` no conoce HTTP; agregar otro proveedor sigue siendo una clase nueva.
- El protocolo para el modelo real vive en un solo lugar y no altera los tokens del simulado.
- Un fallo del proveedor nunca se ve como un `500` genérico y queda en `error_rate`.
- La caché puede guardar datos personales en Cloudflare: queda apagada por omisión.
