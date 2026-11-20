# 0010. Clave por cliente en una dependencia de FastAPI

Estado: aceptado (publicado el 2026-11-14).

## Contexto

Al publicar el producto en internet, `POST /ask` (que gasta modelo) y `GET /metrics` no pueden
quedar abiertos. Hace falta saber qué cliente hizo cada petición sin que la clave aparezca nunca en
el log, la traza ni un error.

## Decisión

`API_KEYS` (`cliente:clave,...`) se valida al arrancar en `app/security.py`; una entrada mal formada
impide arrancar y el error dice su número y su largo, nunca su valor. Una dependencia
`require_client` en `/ask` y `/metrics` lee `X-API-Key`, la compara con `hmac.compare_digest` contra
todas las claves y guarda en `request.state.client` solo el nombre del cliente. Sin clave o con una
inválida responde `401 {"detail": "invalid or missing API key"}`, antes de validar el cuerpo. `/`,
`/health` y `/docs` (con `/openapi.json`) siguen abiertos. El nombre del cliente va en los eventos
`request`, `agent_run` y `audit`, y en los metadatos de la traza. `api_keys` queda fuera de `repr`.

## Consecuencias

- Cada consumo queda atribuido a un cliente en el log y en LangSmith.
- Rotar o revocar una clave es cambiar `API_KEYS` en Render y reiniciar; no hay base de datos.
- Las pruebas de las sesiones anteriores deben mandar `X-API-Key`.
- La página guarda la clave en `sessionStorage`: se pierde al cerrar la pestaña, a propósito.
