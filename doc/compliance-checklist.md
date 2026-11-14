# Checklist de compliance

Con `ENVIRONMENT=production`, `load_settings` (`app/config.py`, función `_enforce_compliance`)
llama a `production_violations` (`app/compliance.py`) y se niega a arrancar si hay alguna regla
incumplida. El error nombra cada regla por su variable de entorno, nunca un valor. Como `app.main`
crea la aplicación al importarse, uvicorn no levanta y Render no recibe `200` en `/health`.
En `development` (el valor por omisión) estas reglas no se aplican.

## Reglas que impiden arrancar en producción

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| `MODEL_PROVIDER` no puede ser `fake` | `app/compliance.py`, `production_violations` | `tests/test_compliance.py` (caso `fake model`) y el escenario «Production refuses to start with the fake model and no keys» de `tests/features/security.feature` |
| `API_KEYS` debe tener al menos un cliente | `app/compliance.py`, `_key_violations` | Escenario «Production refuses to start with the fake model and no keys» |
| Toda clave de `API_KEYS` mide 16 caracteres o más | `app/compliance.py`, `_key_violations` (`MIN_API_KEY_CHARS`) | `tests/test_compliance.py` (caso `short key`) |
| Con trazas encendidas, `HIDE_INPUTS=true` | `app/compliance.py`, `_tracing_violations` | `tests/test_compliance.py::test_each_unsafe_production_setting_is_reported_without_values[visible trace inputs]` |
| Con trazas encendidas, `HIDE_OUTPUTS=true` | `app/compliance.py`, `_tracing_violations` | `tests/test_compliance.py` (caso `visible trace outputs`) |
| Con todo correcto, el producto arranca | `app/config.py`, `load_settings` | Escenario «Production starts with safe settings» |
| `ENVIRONMENT` solo acepta `development` o `production` (un error de escritura no apaga las reglas) | `app/config.py`, `_environment` | `tests/test_config.py::test_invalid_setting_stops_startup_with_clear_message` (caso `("ENVIRONMENT", "prod")`) |

## Reglas de acceso que valen en todos los ambientes

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| `API_KEYS` mal formada impide arrancar; el error dice el número de entrada y su largo, nunca su valor | `app/security.py`, `parse_api_keys` | `tests/test_security.py` y el escenario «Malformed API keys stop startup without revealing the key» |
| `POST /ask` y `GET /metrics` piden `X-API-Key`; sin clave o con una inválida, `401 {"detail": "invalid or missing API key"}` | `app/main.py`, `_client_dependency` | Escenarios «Protected routes reject a request without a key» y «A wrong key is rejected and never reaches the log» |
| La clave se revisa antes de validar el cuerpo | `app/main.py`, dependencia `require_client` | Escenario «The key is checked before the question is validated» |
| `/`, `/health` y `/docs` no piden clave | `app/main.py`, `create_app` | Escenario «Public routes need no key» |
| Las claves se comparan con `hmac.compare_digest` contra todas, sin cortar al primer acierto | `app/security.py`, `ApiKeyAuthenticator.client_for` | `tests/test_security.py` y revisión de código |
| La clave nunca va al log, la traza, un error ni `repr` | `app/config.py` (`api_keys` con `repr=False`), `app/main.py` (solo `request.state.client`), `app/tracing.py` (`request_context` recibe solo el cliente) | `tests/test_config.py`, `tests/test_tracing.py` y el escenario «A valid key answers and only the client name is logged» |
| El nombre del cliente va en `request`, `agent_run`, `audit` y en los metadatos de la traza | `app/main.py`, `app/agent.py`, `app/tracing.py` | Escenario «A valid key answers and only the client name is logged» y `tests/test_tracing.py` |
| Más de `RATE_LIMIT_PER_MINUTE` peticiones por minuto: `429 {"detail": "rate limit exceeded"}` con `Retry-After` | `app/rate_limit.py`, `RateLimiter.check`, y `app/main.py`, `_client_dependency` | `tests/test_rate_limit.py` y los escenarios de límite de `tests/features/security.feature` |
| La página guarda la clave solo en `sessionStorage` y la manda en `X-API-Key` | `app/static/index.html` | `tests/test_api.py` y las pruebas de punta a punta de `e2e/` |
