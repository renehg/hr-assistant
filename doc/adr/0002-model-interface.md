# 0002. Modelo detrás de la interfaz `complete(messages)`

Estado: Ampliado por 0009

Nota: este ADR ya no describe por sí solo el código vigente. Los proveedores aceptados (`fake` y
`gateway`) están definidos en el ADR 0009 (`0009-gateway-provider.md`), y la interfaz del modelo
ahora vive en `app/completion.py` (antes `app/llm.py`).

## Contexto

En esta sesión solo existe un modelo simulado, pero después se usará un modelo real. El agente y las
pruebas no deben depender de un proveedor concreto ni de la red.

## Decisión

`app/llm.py` define la interfaz `complete(messages)` que devuelve texto JSON y conteo de tokens. El
`FakeModel` determinista aplica las reglas del spec. `MODEL_PROVIDER` elige la implementación; en esta
sesión solo se acepta `fake` y cualquier otro valor impide arrancar.

## Consecuencias

- Agregar un proveedor real es crear una clase nueva sin tocar `agent.py`.
- Las pruebas son rápidas, gratuitas y reproducibles; pueden inyectar modelos con guion propio.
- El conteo de tokens del simulado es aproximado (por palabras) y no sirve para estimar costos reales.
