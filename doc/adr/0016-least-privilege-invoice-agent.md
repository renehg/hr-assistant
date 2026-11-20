# 0016. Agente de facturación con mínimo privilegio sobre el mismo bucle

Estado: propuesto. Extiende el ADR 0003.

## Contexto

La spec pide que el agente de facturación use el mismo bucle con tope de la sesión 1 y que nunca
pueda llamar las herramientas del directorio de empleados. Hoy `Agent` trae sus dos herramientas
fijas en el constructor y el gateway agrega siempre el prompt de RH.

## Decisión

- `Agent` recibe sus herramientas inyectadas (validar argumentos, ejecutar, campos de auditoría) y
  un `system_prompt` opcional. El bucle, el tope, los tokens y el costo no cambian.
- `create_app` construye una sola vez el agente de RH, con `get_employee` y
  `search_by_department`. El agente de facturación se construye en cada petición, dentro de
  `InvoiceHandler._run_agent` (`app/invoice_api.py`), con solo la herramienta `crear_factura` de
  esa petición y un prompt que empieza con `[factura]`. Así la herramienta y su resultado no se
  comparten entre peticiones.
- Si la conversación trae su propio mensaje de sistema, el gateway no agrega el prompt de RH. El
  modelo simulado usa `[factura]` para cambiar de reglas.
- Solo cuenta la primera llamada válida a `crear_factura`; las siguientes reciben un error y no
  cambian el resultado.

## Consecuencias

- Pedir `get_employee` desde la factura da «la herramienta no existe»; una prueba lo exige.
- Un solo bucle que mantener; `/ask` conserva su comportamiento y sus pruebas.
- Construir el agente por petición solo arma un objeto con dependencias ya creadas (modelo,
  logger, precios) y evita estado compartido entre peticiones.
- Agregar otro agente es construir otra instancia con otras herramientas, sin tocar el bucle.
