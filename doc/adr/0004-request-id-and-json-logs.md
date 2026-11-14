# 0004. Request id y log JSON a stdout sin datos personales

Estado: propuesto

## Contexto

Soporte necesita contestar "qué pasó con la petición X". Hoy no hay forma de unir lo que vio la
persona con lo que hizo el agente, y el log no puede llevar preguntas ni respuestas porque hablan
de empleados.

## Decisión

Un middleware asigna un `request_id` por petición (el `X-Request-ID` del cliente si es válido, si
no un UUID4) y lo devuelve en el encabezado y en el cuerpo de `/ask`. Un `JsonLogger` escribe una
línea JSON por evento en stdout (`request`, `agent_run`, `audit`, `error`) con `ts`, `service`,
`event` y `request_id`. El id se pasa de forma explícita al agente, no por variables globales. La
hora viene de un `Clock` inyectado. `agent_run` solo lleva conteos; `error` solo el tipo.

## Consecuencias

- Cualquier petición se reconstruye filtrando el log por `request_id`.
- Stdout deja la recolección a la plataforma (12 factores); el producto no maneja archivos.
- Diagnosticar contenido exige reproducir la pregunta: el log, a propósito, no la tiene.
- Pruebas deterministas: reloj y flujo de salida se inyectan en `create_app()`.
