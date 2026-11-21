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
| `PII_MASKING` debe valer `true` | `app/compliance.py`, `production_violations` | Escenario «Production refuses to start without personal data masking» de `tests/features/invoice.feature` |

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
| `POST /invoice` pide `X-API-Key` y comparte el límite de peticiones con `/ask` | `app/main.py`, ruta `invoice` con `require_client` | Escenario «An invoice without a key is rejected» de `tests/features/invoice.feature` |

## Facturas: validación de salida y datos personales (PII)

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| El modelo no manda precios, ids ni totales; si los manda, se descartan | `app/invoice_agent.py`, `_parse_arguments` | `tests/features/invoice.feature` (los cuatro totales exactos) |
| El agente de facturación solo conoce `crear_factura` (mínimo privilegio) | `app/invoice_api.py`, `InvoiceHandler._run_agent` (`tools=[...]`) y `app/agent.py` | `tests/test_invoice_api.py::test_invoice_agent_cannot_call_the_employee_directory` |
| Cliente y conceptos se resuelven contra el catálogo cerrado; el cliente debe aparecer en la frase | `app/catalog.py`, `app/invoice.py`, `app/invoice_agent.py` (`_check_client_in_phrase`) | Escenarios de `422` de `tests/features/invoice.feature` |
| Cantidades de 1 a `MAX_LINE_QUANTITY` y hasta `MAX_INVOICE_LINES` líneas | `app/invoice.py`, `InvoiceService._check_ranges` | `tests/test_invoice_api.py::test_too_many_lines_are_rejected` y el escenario con `0 horas` |
| Todo el dinero con `Decimal`; IVA 16 % redondeado mitad hacia arriba | `app/invoice.py`, `money` y `vat_of` | `tests/features/invoice.feature` (subtotal, IVA y total exactos) |
| **Validación de salida**: antes de responder se revisan el esquema, que cliente y conceptos existan en el catálogo y que importes, subtotal, IVA y total se recalculen igual; si no cuadra, `500 {"detail": "invoice failed validation"}`, evento `audit` y ninguna factura | `app/invoice_validation.py`, `validate_invoice` (independiente de `app/invoice.py`), llamado en `app/invoice_api.py`, `InvoiceHandler._respond` | `tests/test_invoice_api.py::test_invoice_that_fails_validation_is_never_returned` |
| Los errores de negocio responden `422` con el motivo en español y dejan un `audit` `invoice_rejected` | `app/invoice_api.py`, `InvoiceHandler._reject` | Escenario «A business error is answered in Spanish and audited» |
| **PII**: RFC, CURP, correo y teléfono se detectan en la frase y en la respuesta del modelo; `pii_detected` lleva solo tipos | `app/pii.py`, `detect`; `app/invoice_api.py`, `InvoiceHandler.handle` | `tests/test_pii.py` y el escenario «An email in the phrase is detected but never logged nor sent to the model» |
| **PII**: con `PII_MASKING=true` la frase llega al modelo enmascarada (`[RFC]`, `[CURP]`, `[EMAIL]`, `[TELEFONO]`) y el resultado de la herramienta lleva el RFC parcial (`FLO*****AB1`) | `app/pii.py`, `mask` y `mask_rfc`; `app/invoice_agent.py`, `InvoiceTool._for_model` | Escenarios del correo y «The person sees the full RFC but the model only sees it masked» |
| **PII**: el log, la auditoría y las trazas nunca llevan valores, solo tipos; la factura completa se guarda fuera de lo trazado | `app/invoice_api.py` (`_audit` solo con folio, id, total, motivo o tipos) y `app/invoice_agent.py` (`InvoiceOutcome`) | Pasos «the log does not contain» de `tests/features/invoice.feature` |
| La persona autenticada recibe el RFC completo del cliente | `app/invoice_api.py`, `InvoiceResponse` | Escenario «The person sees the full RFC but the model only sees it masked» |
| `/metrics` cuenta `invoices_created`, `invoices_rejected` y `pii_detected` | `app/metrics.py` | Escenario «The metrics count created and rejected invoices and personal data» |
| La página pinta la factura solo con `textContent` | `app/static/index.html`, sección «Factura» | `tests/test_invoice_api.py::test_home_page_has_the_invoice_section_without_inner_html` |
