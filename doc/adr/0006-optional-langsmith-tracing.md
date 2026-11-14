# 0006. Trazas opcionales en LangSmith, privadas por omisión

Estado: propuesto

## Contexto

El log dice qué pasó, pero no cómo razonó el agente vuelta por vuelta. LangSmith lo muestra, pero
es un servicio externo: no debe ser requisito para correr ni recibir datos de empleados sin
permiso.

## Decisión

Un módulo `tracing.py` concentra el uso de `langsmith.traceable` sobre `Agent.run`,
`LanguageModel.complete` y cada herramienta, con `request_id` en los metadatos. Solo se activa si
`LANGSMITH_TRACING=true` y existe `LANGSMITH_API_KEY`; si no, entrega un decorador nulo y no abre
conexiones. `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true` por omisión. La clave la lee el SDK del
entorno; el producto nunca la guarda ni la registra.

## Consecuencias

- El producto funciona igual sin red ni clave; las pruebas no dependen de LangSmith.
- Con ocultamiento activo se ve la forma de la corrida (pasos, herramientas, tiempos), no el
  contenido; mostrarlo es una decisión explícita de quien opera.
- Cambiar de proveedor de trazas solo toca `tracing.py`.
