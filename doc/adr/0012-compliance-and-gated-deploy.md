# 0012. Compliance al arrancar y publicación solo con CI en verde

Estado: propuesto.

## Contexto

Un error de configuración en producción (modelo simulado, claves débiles, trazas con datos
personales) no debe depender de que alguien lo note. Y nada debe llegar a Render sin pasar las
mismas pruebas que corre la fábrica.

## Decisión

`app/compliance.py` expone `production_violations(settings)`. Con `ENVIRONMENT=production`,
`load_settings` lo llama y lanza `ValueError` si `MODEL_PROVIDER=fake`, si `API_KEYS` está vacía o
alguna clave tiene menos de 16 caracteres, o si las trazas están encendidas sin `HIDE_INPUTS=true` y
`HIDE_OUTPUTS=true`. El mensaje nombra las reglas, nunca los valores. Como `app.main` crea la
aplicación al importarse, uvicorn no levanta. `doc/compliance-checklist.md` lista cada regla, dónde
vive y qué prueba la comprueba.

El producto se empaqueta con `Dockerfile` (`python:3.12-slim`, usuario no root). El CI de GitHub
corre `style`, `unit`, `e2e` y `docker` encadenados con `needs`. `render.yaml` usa `runtime: docker`,
`healthCheckPath: /health` y `autoDeployTrigger: checksPass`; los secretos llevan `sync: false`.

## Consecuencias

- Una configuración insegura falla al desplegar (Render no recibe `200` en `/health`), no en uso.
- En `development` no se aplican las reglas: las pruebas y el e2e usan el modelo simulado.
- Publicar exige dos llaves: la aprobación de una persona y el CI en verde.
- `LANGSMITH_API_KEY` no va en el Blueprint (Render exige valor a cada secreto); se agrega a mano.
