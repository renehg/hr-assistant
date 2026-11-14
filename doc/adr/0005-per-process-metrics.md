# 0005. Métricas en memoria por proceso con SLO de p95

Estado: propuesto

## Contexto

Se pide `GET /metrics` con latencia p50/p95, tasa de error, tokens y cumplimiento del SLO. La API
es sin estado (ADR 0001) y escala corriendo más copias, así que no hay un lugar compartido donde
guardar contadores.

## Decisión

Cada proceso lleva sus métricas en memoria en un objeto `Metrics` inyectado en `create_app()`. Las
latencias se guardan en una ventana acotada (últimas 1000) y los percentiles usan rango más
cercano. `error_rate` es respuestas 5xx entre peticiones. `slo.met` es `p95 < SLO_P95_MS`. La
respuesta incluye `pid` para saber qué copia contestó.

## Consecuencias

- Cero dependencias nuevas y nada que pueda caerse aparte del propio proceso.
- Las métricas se pierden al reiniciar y no son globales; agregarlas entre copias es tarea de un
  recolector externo.
- Es estado en memoria, pero solo de telemetría: no afecta ninguna respuesta de `/ask`, así que el
  ADR 0001 sigue vigente.
