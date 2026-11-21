# 0014. El modelo interpreta, el código calcula

Estado: propuesto.

## Contexto

`POST /invoice` convierte una frase en un borrador de factura. Un modelo de lenguaje puede inventar
clientes, precios o sumas, redondear mal o cambiar de opinión entre llamadas. Un error de dinero en
una factura, aunque sea un borrador, no es aceptable.

## Decisión

- El modelo solo pide `crear_factura(cliente, conceptos)` con el texto del cliente y pares
  `{concepto, cantidad}`. Nunca manda precios, ids ni totales; si los manda, se ignoran.
- El código resuelve cliente y conceptos contra un catálogo cerrado (`data/clientes.json`,
  `data/conceptos.json`), sin acentos ni mayúsculas, con el alias más largo y sin traslapes. El
  alias del cliente debe aparecer en la frase.
- El código revisa rangos, calcula importes, subtotal, IVA (16 %, mitad hacia arriba) y total con
  `Decimal`, y devuelve el dinero como texto con 2 decimales.
- Antes de responder, un validador independiente recalcula todo contra el catálogo; si algo no
  cuadra, `500 invoice failed validation` sin factura.
- La respuesta usa la factura guardada por el código, nunca el texto final del modelo.

## Consecuencias

- Los totales son deterministas y se prueban sin modelo; el simulado basta para el contrato.
- Solo existen los clientes y conceptos del catálogo; agregar uno es cambiar un JSON.
- Las frases que el modelo malinterpreta terminan en `422` con un motivo en español, no en una
  factura equivocada.
- Hay dos implementaciones del cálculo (servicio y validador); es duplicación intencional.
