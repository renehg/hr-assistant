# 0013. Secretos de producción: error completo al arrancar y ensayo en el CI

Estado: propuesto. Complementa el ADR 0012.

## Contexto

En la primera publicación (2026-11-14) el CI pasó, pero Render no arrancó porque `CF_ACCOUNT_ID`
estaba vacía. Los secretos tienen `sync: false` y una persona los escribe a mano, así que pueden
faltar. Además, el error nombraba solo el primer problema: `load_settings` cortaba en la primera
`CF_*` que faltaba, antes de revisar compliance, así que `CF_API_TOKEN` o una `API_KEYS` vacía
habrían costado otro despliegue cada una. El CI nunca arrancaba la imagen como lo hace Render:
siempre usaba `ENVIRONMENT=development` y el modelo simulado.

## Decisión

- `load_settings`, con `MODEL_PROVIDER=gateway`, junta las variables `CF_*` que faltan y, con
  `ENVIRONMENT=production`, también las reglas de compliance incumplidas, y las nombra todas en un
  solo error, en orden fijo y sin valores. Los errores de formato siguen cortando antes.
- El trabajo `docker` del CI ensaya dos arranques de la imagen: con la forma de Render
  (`ENVIRONMENT=production`, `gateway`, ocultamiento encendido, clave y `CF_*` de ejemplo a la vista
  en `ci.yml`) debe responder `200` en `/health`; con `ENVIRONMENT=production`, `fake` y una clave
  válida debe terminar sin servir, en tiempo acotado, nombrando `MODEL_PROVIDER` en su log y sin
  mostrar la clave. El ensayo no llama a Cloudflare: el modelo real solo usa la red en `/ask`.
- Antes de aprobar la publicación, la persona confirma en Render > Environment que existen
  `API_KEYS`, `CF_ACCOUNT_ID` y `CF_API_TOKEN`, y define `SMOKE_API_KEY` en su terminal.

## Consecuencias

- Los secretos que faltan cuestan un despliegue, no uno por variable, y el log de Render lo dice
  todo.
- Una regresión en el arranque de producción (compliance, imports, rutas de datos) falla en el CI,
  antes de llegar a Render.
- El CI no prueba que los secretos reales sean correctos; eso sigue siendo trabajo de la prueba de
  humo y de la persona.
- Los valores de ejemplo de `ci.yml` no son secretos y no sirven en Render; un comentario lo dice.
