Feature: A simple invoice draft from a natural language phrase
  A person writes a phrase and gets a draft invoice. The model only reads the
  phrase; the code finds the client, takes the prices from the catalog,
  computes the VAT and checks the result. Nothing is stamped and personal data
  never reaches the log.

  Scenario Outline: A valid phrase becomes a draft invoice with the exact total
    Given the invoice assistant is running with a fixed clock and folio
    When I ask for the invoice "<phrase>"
    Then the response status is 200
    And the invoice is a draft in MXN for the client "<client_id>"
    And the invoice has subtotal "<subtotal>", VAT "<vat>" and total "<total>"
    And the only tool used is "crear_factura"

    Examples:
      | phrase                                                                                             | client_id | subtotal | vat     | total    |
      | Fáctrale a Ferretería López 10 horas de consultoría fiscal y 2 paquetes de timbres                 | CLI-001   | 9200.00  | 1472.00 | 10672.00 |
      | Factura para Panadería El Trigal: 1 licencia mensual de software                                   | CLI-005   | 1500.00  | 240.00  | 1740.00  |
      | Genera una factura a Transportes del Norte por 1 integración con ERP y 3 sesiones de capacitación  | CLI-003   | 19500.00 | 3120.00 | 22620.00 |
      | Cobra a Clínica Dental Sonrisa 4 horas de soporte técnico                                          | CLI-004   | 2400.00  | 384.00  | 2784.00  |

  Scenario Outline: A business error is answered in Spanish and audited
    Given the invoice assistant is running with a fixed clock and folio
    When I ask for the invoice "<phrase>"
    Then the response is 422 with the detail "<detail>"
    And an "invoice_rejected" audit event gives the reason "<detail>"

    Examples:
      | phrase                                                 | detail                                        |
      | Factura a Cliente Fantasma 1 licencia mensual          | cliente no encontrado                         |
      | Factura a Abarrotes La Esperanza 2 helicópteros        | no se reconoció ningún concepto del catálogo  |
      | Factura a Ferretería López 0 horas de soporte técnico  | cantidad o número de líneas fuera de rango    |

  Scenario: An email in the phrase is detected but never logged nor sent to the model
    Given the invoice assistant is running with a fixed clock and folio
    When I ask for the invoice "Factura a Ferretería López 1 licencia, mi correo es ana@ejemplo.com"
    Then the response status is 200
    And the detected personal data is only "email"
    And the log does not contain "ana@ejemplo.com"
    And the model never received "ana@ejemplo.com"

  Scenario: The person sees the full RFC but the model only sees it masked
    Given the invoice assistant is running with a fixed clock and folio
    When I ask for the invoice "Cobra a Ferretería López 4 horas de soporte técnico"
    Then the invoice shows the client RFC "FLO010101AB1"
    And the model received "FLO*****AB1"
    And the model never received "FLO010101AB1"
    And the log does not contain "FLO010101AB1"

  Scenario: An invoice without a key is rejected
    Given the invoice assistant is running without a key
    When I ask for the invoice "Cobra a Clínica Dental Sonrisa 4 horas de soporte técnico"
    Then the response is 401 with the detail "invalid or missing API key"

  Scenario: An empty phrase is rejected before reaching the model
    Given the invoice assistant is running with a fixed clock and folio
    When I ask for an invoice with an empty phrase
    Then the response status is 422
    And the model was never called

  Scenario: The metrics count created and rejected invoices and personal data
    Given the invoice assistant is running with a fixed clock and folio
    When I ask for the invoice "Cobra a Clínica Dental Sonrisa 4 horas de soporte técnico"
    And I ask for the invoice "Factura a Cliente Fantasma 1 licencia mensual"
    And I ask for the invoice "Factura a Ferretería López 1 licencia, mi correo es ana@ejemplo.com"
    Then the metrics report 2 invoices created, 1 rejected and 1 with personal data

  Scenario: Production refuses to start without personal data masking
    When the product starts in production with safe settings but PII_MASKING "false"
    Then startup fails naming "PII_MASKING"
