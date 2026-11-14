# 0008. Costo calculado en el producto con una tabla de precios local

Estado: propuesto

## Contexto

Cada palanca se acepta solo si baja el costo sin bajar la calidad. Para medirlo sin red, el modelo
simulado también debe costar, y el costo debe salir en cada respuesta y en `/metrics`.

## Decisión

`app/pricing.py` carga `data/model_prices.json` (USD por millón de tokens) y calcula
`(input * precio_entrada + output * precio_salida) / 1 000 000` por llamada, sin redondear. Una
llamada con `cf-aig-cache-status: HIT` cuenta en `cached_calls` y cuesta 0. Los modelos simulados se
llaman como `MODEL_SMALL` y `MODEL_LARGE` y usan su precio. Si alguno de los dos no tiene precio, la
aplicación no arranca.

## Consecuencias

- La evaluación compara línea base y palancas sin red y sin gastar cuota.
- El costo es una estimación: con `fake` los tokens se cuentan por palabras; con `gateway`, desde
  `usage`. La factura real de Cloudflare manda.
- Los precios cambian: hay que revisar la fecha `checked` y volver a copiar el archivo.
- Sin redondeo, una pregunta corta nunca reporta costo 0 por error.
