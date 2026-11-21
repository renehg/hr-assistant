# 0015. PII enmascarada antes del modelo; solo tipos en logs y trazas

Estado: propuesto. Complementa los ADR 0006 y 0012.

## Contexto

Las frases de factura pueden traer RFC, CURP, correos o teléfonos, y la herramienta devuelve el
RFC del cliente. El modelo real es un servicio externo y las trazas pueden ir a LangSmith. La
persona autenticada sí necesita el RFC del cliente en la factura.

## Decisión

- `app/pii.py` detecta RFC, CURP, correo y teléfono de 10 dígitos con los patrones de la spec y
  reporta solo tipos (`rfc`, `curp`, `email`, `phone`), en orden fijo y sin repetir.
- Con `PII_MASKING=true` (por omisión) la frase llega al modelo enmascarada (`[RFC]`, `[CURP]`,
  `[EMAIL]`, `[TELEFONO]`) y el resultado de la herramienta lleva el RFC del cliente parcial
  (`FLO*****AB1`). Se enmascara primero la CURP, porque contiene algo con forma de RFC.
- Logs, auditoría y trazas nunca llevan textos; el evento `pii_detected` lleva solo tipos. La
  factura completa se guarda fuera de las funciones trazadas.
- `pii_detected` une lo encontrado en la frase y en las respuestas del modelo; el RFC del catálogo
  dentro de la factura no cuenta.
- Con `ENVIRONMENT=production`, `PII_MASKING` distinto de `true` impide arrancar.

## Consecuencias

- El proveedor del modelo y LangSmith no reciben datos personales de la frase.
- Los patrones son simples: formatos con espacios o guiones no se detectan; se acepta y se
  documenta.
- Desactivar el enmascarado solo es posible en desarrollo.
