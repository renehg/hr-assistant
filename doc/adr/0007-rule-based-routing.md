# 0007. Enrutamiento por regla en código, una vez por petición

Estado: propuesto

## Contexto

La mayoría de las preguntas (un empleado, un departamento) las resuelve un modelo pequeño; pocas
necesitan uno capaz. Usar otro modelo para decidir costaría tokens y haría la decisión no
reproducible.

## Decisión

`app/router.py` expone `choose_route(question, settings) -> Route(model, reason)`. Es una función
pura: `MODEL_LARGE` si `ROUTING=false`, si la pregunta pasa de `ROUTER_MAX_CHARS` o si contiene una
palabra clave del spec (sin distinguir mayúsculas); si no, `MODEL_SMALL`. Se decide una vez por
petición y todas las vueltas del agente usan ese modelo. El motivo es un código fijo
(`routing_disabled`, `long_question`, `keyword:<palabra>`, `default`), nunca texto de la persona.

## Consecuencias

- Decisión gratuita, instantánea y fácil de probar en sus límites.
- El motivo puede ir en la respuesta y en `agent_run` sin exponer datos personales.
- Habrá falsos positivos («resumen», «todos»): encarecen, no empeoran la respuesta.
- La regla no mide la calidad del modelo pequeño real; eso lo cubre la evaluación.
