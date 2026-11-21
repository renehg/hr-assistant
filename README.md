# HR Assistant

Asistente de Recursos Humanos: una API web sin estado y una página que responden preguntas sobre
el directorio de empleados (`data/employees.json`) con un agente de bucle con tope y dos
herramientas de solo lectura (`get_employee` y `search_by_department`).

Desde la sesión 2 cada petición se puede rastrear y medir:

- **Id por petición.** Si el cliente manda `X-Request-ID` (hasta 128 caracteres ASCII imprimibles)
  se respeta; si no, se genera un UUID. Toda respuesta lo devuelve en el encabezado `X-Request-ID`,
  y `POST /ask` también en el cuerpo como `request_id`. La página web lo muestra para que la
  persona lo pase a soporte.
- **Log JSON** en la salida estándar, una línea por evento, con `ts` (UTC), `service`, `event` y
  `request_id`. Eventos: `request`, `agent_run` (solo conteos, nunca textos), `audit` (una por
  herramienta) y `error` (solo el tipo de la excepción). Un error interno responde
  `500 {"detail": "internal error", "request_id": ...}`.
- **Métricas** del proceso en `GET /metrics`: peticiones, tasa de errores 5xx, latencia p50/p95,
  tokens y si se cumple el SLO de p95. Cada copia reporta solo lo suyo (ver `pid`).
- **Trazas opcionales en LangSmith**, privadas por omisión.

Desde la sesión 3 cada respuesta dice qué modelo usó, por qué y cuánto costó:

- **Modelo real** con `MODEL_PROVIDER=gateway`: Cloudflare Workers AI a través de AI Gateway
  (`CF_ACCOUNT_ID`, `CF_GATEWAY_ID`, `CF_API_TOKEN`). Si el gateway falla, `POST /ask` responde
  `502 {"detail": "model unavailable", "request_id": ...}`.
- **Enrutamiento por regla** (`ROUTING`): las preguntas de más de `ROUTER_MAX_CHARS` caracteres o
  con «compara», «resume», «explica», «por qué», «analiza» o «todos» van a `MODEL_LARGE`; el resto
  a `MODEL_SMALL`. El motivo sale en `route` (`default`, `long_question`, `keyword:<palabra>` o
  `routing_disabled`).
- **Ventana de historial** (`HISTORY_WINDOW`): al modelo solo llegan los últimos mensajes.
- **Tope de salida** (`MODEL_MAX_TOKENS`) en cada llamada.
- **Caché de AI Gateway** (`CACHE_TTL_SECONDS`, apagada con `0`): una llamada servida desde la
  caché (`cf-aig-cache-status: HIT`) cuenta en `cached_calls` y no cuesta. La caché guarda
  respuestas en Cloudflare, que pueden tener datos personales: usa un TTL corto.
- **Costo por respuesta** con los precios de `data/model_prices.json` (USD por millón de tokens,
  copia de `spec/model_prices.json`; revisa la fecha `checked`). `POST /ask` agrega `model`,
  `route`, `cached_calls` y `cost_usd`; `GET /metrics` agrega `cost_usd` acumulado. Con `fake` hay
  dos modelos simulados que se llaman como `MODEL_SMALL` y `MODEL_LARGE`: responden igual pero
  cuestan según su nombre, así las palancas se miden sin red.

Desde la sesión 4 el producto está cerrado para publicarse:

- **Una clave por cliente.** `API_KEYS` tiene la forma `cliente:clave,cliente2:clave2`.
  `POST /ask` y `GET /metrics` piden el encabezado `X-API-Key`; sin clave o con una inválida
  responden `401 {"detail": "invalid or missing API key"}`, antes de validar el cuerpo. `GET /`,
  `GET /health` y `/docs` no piden clave. Las claves se comparan con `hmac.compare_digest`. El
  nombre del cliente va en el campo `client` de los eventos `request`, `agent_run` y `audit`, y en
  los metadatos de la traza; **la clave nunca** se escribe en el log, la traza, un error ni en
  `repr` de la configuración. Una `API_KEYS` mal formada impide arrancar y el error dice qué
  entrada falla y su largo, nunca su valor.
- **Límite de peticiones por cliente.** Más de `RATE_LIMIT_PER_MINUTE` peticiones en una ventana
  deslizante de 60 segundos responden `429 {"detail": "rate limit exceeded"}` con `Retry-After`
  (segundos que faltan). El límite es por proceso: con varias copias se multiplica (ADR 0011).
- **Compliance como código.** Con `ENVIRONMENT=production` el producto se niega a arrancar si
  `MODEL_PROVIDER=fake`, si `API_KEYS` está vacía o alguna clave tiene menos de 16 caracteres, o si
  las trazas están encendidas sin `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`, o si `PII_MASKING` no
  vale `true`. Cada regla, dónde está
  y cómo se comprueba: `doc/compliance-checklist.md`.
- **La página** tiene un campo de clave tipo contraseña. La clave se guarda solo en
  `sessionStorage` (se pierde al cerrar la pestaña) y se manda en `X-API-Key`. Con `401` muestra
  «Clave inválida» y con `429` «Demasiadas preguntas; espera N segundos».

Reto de facturación: **borrador de factura en lenguaje natural** (`POST /invoice`). Es un
borrador **sin validez fiscal**, con datos ficticios: no se timbra ni se guarda nada.

- **El modelo interpreta, el código calcula** (ADR 0014). El agente de facturación solo conoce la
  herramienta `crear_factura(cliente, conceptos)`; nunca puede usar las del directorio de
  empleados (ADR 0016). El modelo manda el texto del cliente y pares `{concepto, cantidad}`;
  precios, ids o totales que mande se descartan.
- **Catálogo cerrado** en `data/clientes.json` y `data/conceptos.json` (copias de `spec/`). Cliente
  y conceptos se buscan sin acentos ni mayúsculas en `nombre` y `aliases`; gana el alias más
  largo, sin traslapes. El cliente debe aparecer en la frase.
- **Reglas de negocio**: cantidades enteras de 1 a `MAX_LINE_QUANTITY`, hasta `MAX_INVOICE_LINES`
  líneas; `importe = cantidad × precio_unitario`, IVA 16 % redondeado mitad hacia arriba, todo con
  `Decimal` y en la respuesta como texto con 2 decimales (`"1740.00"`), moneda `MXN`.
- **Errores de negocio**: `422 {"detail": ...}` con `cliente no encontrado`, `no se reconoció
  ningún concepto del catálogo` o `cantidad o número de líneas fuera de rango` (y `no se pudo
  interpretar la factura` si el modelo no usa la herramienta).
- **Validación de salida**: antes de responder, un validador independiente revisa el esquema, el
  catálogo y recalcula importes, subtotal, IVA y total. Si algo no cuadra responde
  `500 {"detail": "invoice failed validation"}` sin factura.
- **Datos personales (PII)**: RFC, CURP, correo y teléfono de 10 dígitos se detectan en la frase y
  en la respuesta del modelo; `pii_detected` lista solo tipos (`rfc`, `curp`, `email`, `phone`).
  Con `PII_MASKING=true` el modelo recibe la frase enmascarada (`[EMAIL]`...) y el RFC del cliente
  parcial (`FLO*****AB1`); la persona autenticada sí ve el RFC completo. Log, auditoría y trazas
  nunca llevan valores (ADR 0015). En producción `PII_MASKING` debe ser `true`.
- **Auditoría y métricas**: eventos `audit` con `client` y `request_id`: `invoice_created` (folio,
  id del cliente, total), `invoice_rejected` (motivo) y `pii_detected` (tipos). `GET /metrics`
  agrega `invoices_created`, `invoices_rejected` y `pii_detected`.
- **La página** tiene una sección «Factura»: escribe la frase, pulsa «Crear borrador» y ve el
  cliente, la tabla de líneas, subtotal, IVA y total; con `422` muestra el mensaje del servidor.

Ejemplo (la clave se lee de una variable, nunca escrita en el comando):

```bash
curl -X POST http://localhost:8000/invoice \
  -H "X-API-Key: $HR_API_KEY" -H "Content-Type: application/json" \
  -d '{"text": "Cobra a Clínica Dental Sonrisa 4 horas de soporte técnico"}'
```

Responde `invoice` (`folio`, `fecha`, `estado: "borrador"`, `moneda: "MXN"`, `cliente`, `lineas`,
`subtotal: "2400.00"`, `iva: "384.00"`, `total: "2784.00"`), `steps`, `tools_used`
(`["crear_factura"]`), `input_tokens`, `output_tokens`, `cost_usd`, `request_id` y
`pii_detected`.

La arquitectura y las decisiones están en `doc/architecture.md` y `doc/adr/`.

## Cómo correrlo

Desde la carpeta `product/`, con las dependencias de `requirements.txt` instaladas, define al
menos un cliente en `API_KEYS` (inventa tu propia clave; nunca la subas al repositorio):

```bash
export API_KEYS="mi-equipo:<tu-clave-de-16-o-mas-caracteres>"
uvicorn app.main:app --port 8000
```

Abre `http://localhost:8000/`, escribe tu clave en el campo «Clave de acceso» y pregunta. Rutas:

| Ruta | Clave | Para qué |
| --- | --- | --- |
| `GET /` | No | Página web |
| `GET /health` | No | Estado y `pid` de la copia |
| `GET /docs` | No | Documentación de la API |
| `POST /ask` | `X-API-Key` | Cuerpo `{"question": "...", "history": [...]}` |
| `POST /invoice` | `X-API-Key` | Cuerpo `{"text": "..."}`; borrador de factura sin validez fiscal |
| `GET /metrics` | `X-API-Key` | Métricas de este proceso |

Desde la terminal, la clave va en el encabezado (léela de una variable, no la escribas en el
comando):

```bash
curl -H "X-API-Key: $HR_API_KEY" http://localhost:8000/metrics
```

Para encontrar todo lo que pasó con una petición, filtra el log por su id:

```bash
uvicorn app.main:app --port 8000 | grep '"request_id": "demo-123"'
```

## Pruebas

Desde la raíz del repositorio:

```bash
uv run python -m verification unit
uv run python -m verification qa
uv run python -m verification evaluate
```

Ninguna prueba sale a la red: el cliente HTTP del gateway se inyecta y las pruebas usan
`httpx.MockTransport`.

Las pruebas de la factura en `tests/`:

- `features/invoice.feature` (pasos en `test_invoice_steps.py`), con reloj y folio fijos: cuatro
  frases válidas dan borradores en MXN con subtotal, IVA y total exactos y solo usan
  `crear_factura`; los tres errores de negocio responden `422` en español y dejan un evento
  `invoice_rejected`; un correo en la frase se detecta pero no llega al log ni al modelo; la
  persona ve el RFC completo y el modelo solo el enmascarado; sin clave responde `401`; una frase
  vacía se rechaza sin llamar al modelo; las métricas cuentan facturas creadas, rechazadas y con
  PII; y producción no arranca con `PII_MASKING=false`.
- `test_invoice_api.py`: una factura que no pasa la validación de salida nunca se devuelve, el
  agente de facturación no puede usar el directorio de empleados, demasiadas líneas se rechazan y
  la página trae la sección «Factura» sin `innerHTML`.
- `test_pii.py`: detección de RFC, CURP, correo y teléfono (orden fijo, sin repetidos, una CURP
  no cuenta también como RFC, un teléfono pegado a otros dígitos no cuenta) y enmascarado de cada
  valor con su etiqueta.
- `test_catalog.py`: la normalización quita acentos, mayúsculas y espacios de más; gana el alias
  más largo sin traslapes y solo con palabras completas («3 licencias» no cuenta como
  «licencia»); un catálogo con id repetido, RFC mal formado, alias vacío, precio sin centavos o
  en cero no carga (y el error no trae el RFC); el catálogo real resuelve clientes y conceptos.
- `test_invoice.py`: redondeo mitad hacia arriba a 2 decimales e IVA; una licencia para
  Ferretería López da `1500.00`, `240.00` y `1740.00` con la fecha en hora de México; cantidades
  enteras de 1 a 1000 (rechaza 0, 1001, booleanos y decimales); 6 líneas se rechazan; un
  concepto desconocido se omite si hay otro conocido; los rechazos se revisan en orden cliente,
  rangos, conceptos; `crear_factura` no acepta un cliente que no está en la frase, solo cuenta
  su primera llamada y al modelo le devuelve la factura sin el RFC completo.
- `test_invoice_validation.py`: una factura correcta pasa la validación de salida, y alterar un
  solo campo (importe, subtotal, IVA, total, cliente o concepto inexistente, precio unitario,
  total que no es texto o un campo faltante) la hace fallar sin poner el RFC en el error.
- `test_agent.py` (facturación): el mensaje de sistema propio va antes del historial y la
  pregunta; el agente de Recursos Humanos no manda mensaje de sistema y conserva sus
  herramientas; las herramientas inyectadas reemplazan a las del directorio (una llamada a
  `get_employee` recibe «no existe» y no se filtran datos de empleados); sin directorio ni
  herramientas el agente no se crea.
- `test_gateway.py` (facturación): un mensaje de sistema propio reemplaza al de Recursos Humanos
  en la petición al gateway, y sin él se manda el de Recursos Humanos.

Las pruebas de punta a punta de la página (`e2e/`) usan pytest-playwright (está en
`requirements.txt`). La primera vez instala el navegador y luego córrelas desde la raíz:

```bash
uv run playwright install chromium
uv run python -m verification e2e
```

`verification e2e` arranca el producto con el modelo simulado (`MODEL_PROVIDER=fake`, sin red)
en un puerto local, con una `API_KEYS` de prueba que inventa la verificación, y pone esa misma
clave en `E2E_API_KEY` para que la página la escriba; luego abre la página en Chromium.

- `e2e/test_chat_page.py` (preguntas): el campo de clave es de tipo contraseña, una pregunta
  muestra la respuesta y su `request_id`, la caja vacía muestra un error en español sin llamar a
  la API, una segunda pregunta se agrega sin borrar la conversación anterior y una clave
  equivocada muestra «Clave inválida».
- `e2e/test_invoice_page.py` (sección «Factura»): una frase para Ferretería López muestra el
  cliente, la tabla de líneas, el subtotal `9200.00`, el IVA `1472.00` y el total `10672.00`; un
  cliente fuera del catálogo muestra «cliente no encontrado» y ninguna tabla.

## Publicar: Docker, CI y Render

### Imagen Docker

Desde `product/`, con la clave en una variable de tu terminal (nunca escrita en el comando):

```bash
docker build -t hr-assistant .
docker run -p 8000:8000 -e API_KEYS="mi-equipo:$HR_API_KEY" hr-assistant
```

La imagen (`python:3.12-slim`, usuario sin root) solo copia `requirements.txt`, `app/` y `data/`;
no lleva claves ni `.env`. Escucha en `$PORT` (8000 por omisión). Para el modelo real agrega
`-e MODEL_PROVIDER=gateway -e CF_ACCOUNT_ID -e CF_API_TOKEN` (sin `=`, Docker toma los valores
de tu entorno).

### CI (`.github/workflows/ci.yml`)

Corre en cada push y pull request; cada etapa necesita la anterior (`needs`) y una falla detiene
las siguientes:

1. `style`: pylint de `app` y `tests`, 88 columnas, nota 10.
2. `unit`: pytest de `tests` (unitarias y BDD) con cobertura mínima de 80 % sobre `app`.
3. `e2e`: arranca el producto con `MODEL_PROVIDER=fake`, espera a que responda en `/health` y
   corre `e2e/` en Chromium.
4. `docker`: construye la imagen, la arranca con el modelo simulado y comprueba que responde en
   `/health`.

El CI usa una clave de ejemplo pública (`CI_API_KEY` en el propio archivo), no un secreto: no
sirve en Render.

### Render (`render.yaml`)

Crea el servicio en Render como Blueprint apuntando al repositorio. Con
`autoDeployTrigger: checksPass` Render publica solo cuando el CI pasa, y con
`healthCheckPath: /health` solo da por buena una versión que responde. El Blueprint fija
`ENVIRONMENT=production`, `MODEL_PROVIDER=gateway`, `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`.

Los secretos `API_KEYS`, `CF_ACCOUNT_ID` y `CF_API_TOKEN` tienen `sync: false`: nunca están en el
repositorio; Render los pide al crear el Blueprint y una persona los escribe a mano (después se
cambian en Render > Environment). En producción cada clave de `API_KEYS` debe tener 16 caracteres
o más. `LANGSMITH_API_KEY` se agrega en Render > Environment solo si enciendes las trazas. Si la
configuración incumple una regla de `doc/compliance-checklist.md`, el producto no arranca y
Render no publica esa versión.

### Prueba de humo

Desde `product/`, con la clave de un cliente de `API_KEYS` en el entorno (nunca como argumento):

```bash
SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com
```

Comprueba `GET /health` (200), `POST /ask` sin clave (401) y `POST /ask` con clave (200), e
imprime `[OK]` o `[FAIL]` con el código recibido; nunca imprime la clave. Sale con 0 si todo
pasa, 1 si falla alguna comprobación y 2 si falta la URL o `SMOKE_API_KEY`. Un 401 con clave
indica que la clave no coincide; un 502, que el modelo no responde. El plan gratuito puede tardar
hasta un minuto en despertar.

### Pruebas de punta a punta y E2E_API_KEY

Las pruebas de `e2e/` leen la clave de `E2E_API_KEY`, que debe coincidir con una clave de
`API_KEYS` del producto que corre. `verification e2e` la pone sola; si corres `pytest e2e` a
mano, arranca antes el producto, exporta la variable y pasa la URL:

```bash
python -m pytest e2e --base-url http://127.0.0.1:8000
```

Sin `E2E_API_KEY` las pruebas que usan la clave fallan.

## Variables de entorno

El producto solo lee variables de entorno (`os.environ`): no lee ningún archivo `.env`.
`.env.example` es una lista de referencia con todas las variables, sus valores por omisión y los
secretos vacíos. Exporta en la terminal las que quieras cambiar antes de arrancar:

```bash
export MODEL_PROVIDER=gateway CF_ACCOUNT_ID=... CF_API_TOKEN=...
uvicorn app.main:app --port 8000
```

Si prefieres un archivo, copia `.env.example` como `.env` (que nunca se sube al repositorio),
llénalo y cárgalo en la misma terminal con `set -a; . ./.env; set +a` antes de `uvicorn`.

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `MODEL_PROVIDER` | `fake` | `fake` (simulado, sin red) o `gateway` (Workers AI) |
| `AGENT_MAX_STEPS` | `3` | Tope de vueltas del agente |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta |
| `EMPLOYEES_PATH` | `data/employees.json` | Archivo de empleados (relativo a `product/`) |
| `SERVICE_NAME` | `hr-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `2000` | Meta de latencia p95 en milisegundos |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas en LangSmith |
| `LANGSMITH_API_KEY` | (sin valor) | Clave de LangSmith; sin ella no hay trazas |
| `HIDE_INPUTS` | `true` | No mandar a LangSmith el texto de las preguntas |
| `HIDE_OUTPUTS` | `true` | No mandar a LangSmith el texto de las respuestas |
| `CF_ACCOUNT_ID` | (sin valor) | Cuenta de Cloudflare (obligatoria con `gateway`) |
| `CF_GATEWAY_ID` | `default` | Id del AI Gateway |
| `CF_API_TOKEN` | (sin valor) | Token de Cloudflare, secreto (obligatorio con `gateway`) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan (0 o más) |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida |
| `MODEL_TEMPERATURE` | `0` | Entre 0 y 2; con 0 las evaluaciones son repetibles |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway en segundos (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo (relativo a `product/`) |
| `ENVIRONMENT` | `development` | `development` o `production`; con `production` se aplican las reglas de compliance |
| `API_KEYS` | (sin valor) | Clientes y claves `cliente:clave,...` (secreto) |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto (1 o más) |
| `CLIENTES_PATH` | `data/clientes.json` | Catálogo de clientes (relativo a `product/`) |
| `CONCEPTOS_PATH` | `data/conceptos.json` | Catálogo de conceptos (relativo a `product/`) |
| `MAX_INVOICE_LINES` | `5` | Máximo de líneas por factura |
| `MAX_LINE_QUANTITY` | `1000` | Cantidad máxima por línea |
| `PII_MASKING` | `true` | Enmascara PII antes del modelo; obligatorio `true` en producción |

Un valor inválido (por ejemplo `SLO_P95_MS=0`, `LANGSMITH_TRACING=quizas` o `MODEL_TEMPERATURE=3`)
impide arrancar con un mensaje que nombra la variable. También impiden arrancar: `gateway` sin
`CF_ACCOUNT_ID` o `CF_API_TOKEN`, y un `MODEL_SMALL` o `MODEL_LARGE` sin precio en `PRICES_PATH`.
El token de Cloudflare nunca aparece en el log, en los errores ni en `repr` de la configuración.
Lo mismo vale para las claves de `API_KEYS`. También impiden arrancar una `API_KEYS` mal formada
(entrada sin `:`, cliente o clave vacíos, cliente repetido), un `ENVIRONMENT` distinto de
`development` o `production`, un `CLIENTES_PATH` o `CONCEPTOS_PATH` que no existe o tiene
entradas inválidas (ids repetidos, RFC o precio con mal formato, alias vacíos) y, con
`ENVIRONMENT=production`, cualquier regla de `doc/compliance-checklist.md` incumplida.

Las trazas solo se activan con `LANGSMITH_TRACING=true` **y** `LANGSMITH_API_KEY`; sin la clave el
producto funciona igual y no intenta conectarse. La clave la lee el SDK de LangSmith del entorno: el
producto nunca la guarda, la muestra ni la escribe en el log. Expórtala en el entorno antes de
arrancar (directamente o cargando un `.env` como se explica arriba); escribirla en un `.env` sin
cargarlo no tiene efecto.


> **Entrega del reto M4.** Servicio en producción: https://hr-assistant-ff0e.onrender.com/docs · Reporte completo con evidencia: [docs/ENTREGA.md](docs/ENTREGA.md)