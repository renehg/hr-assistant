# 0003. Un solo agente con bucle con tope y protocolo JSON

Estado: propuesto

## Contexto

El modelo puede pedir herramientas indefinidamente o responder con un formato inesperado. Sin un
límite, una pregunta podría consumir tiempo y tokens sin fin.

## Decisión

Un único agente con dos herramientas de solo lectura (`get_employee`, `search_by_department`). En
cada vuelta el modelo responde un objeto JSON: `{"tool", "args"}` o `{"answer"}`. El resultado de la
herramienta vuelve como mensaje `user` con prefijo `Resultado de la herramienta: `. El bucle se corta
en `AGENT_MAX_STEPS` (por omisión 3, mínimo 1) y entonces responde el mensaje fijo del spec. Un JSON
inválido o una herramienta desconocida no lanzan excepción hacia la API.

## Consecuencias

- Costo y latencia acotados por diseño y medibles con `steps` y tokens en la respuesta.
- Preguntas que requieran muchas herramientas pueden caer en el mensaje de tope.
- Agregar herramientas es registrar una función más en el agente, sin cambiar el protocolo.
