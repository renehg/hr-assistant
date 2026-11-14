# 0001. API sin estado con historial enviado por el cliente

Estado: propuesto

## Contexto

El HR Assistant debe escalar corriendo más copias de la API. Si una copia guardara la conversación,
cada persona quedaría atada a esa copia y un reinicio perdería datos.

## Decisión

La API no guarda nada entre peticiones. El navegador mantiene el historial y lo envía en `history`
en cada `POST /ask`. Las dependencias (configuración, modelo, directorio) se crean al arrancar, son de
solo lectura y se inyectan en `create_app()`.

## Consecuencias

- Cualquier copia puede atender cualquier petición; `GET /health` expone el `pid` para comprobarlo.
- El cuerpo de la petición crece con la conversación; `MAX_QUESTION_CHARS` limita solo la pregunta.
- El historial no es confiable: se valida su forma y las herramientas son de solo lectura.
