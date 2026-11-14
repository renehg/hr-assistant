Feature: Only known clients use the assistant, within a fair limit
  Every client has its own API key. The key is checked before anything else,
  it is never written anywhere, and production refuses to start with unsafe
  settings.

  Scenario: Protected routes reject a request without a key
    Given the secured HR assistant is running
    When I ask "¿Quién es EMP-0004?" without a key
    And I read the metrics without a key
    Then both responses are 401 with the detail "invalid or missing API key"
    And the metrics read with a valid key report no errors

  Scenario: A wrong key is rejected and never reaches the log
    Given the secured HR assistant is running
    When I ask "¿Quién es EMP-0004?" with the key "wrong-key-that-must-not-leak"
    Then the response is 401 with the detail "invalid or missing API key"
    And the log does not contain "wrong-key-that-must-not-leak"

  Scenario: Public routes need no key
    Given the secured HR assistant is running
    When I open the home page, the health check and the docs without a key
    Then every response is 200

  Scenario: The key is checked before the question is validated
    Given the secured HR assistant is running
    When I ask an empty question without a key
    Then the response is 401 with the detail "invalid or missing API key"

  Scenario: A valid key answers and only the client name is logged
    Given the secured HR assistant is running
    When the client "test-suite" asks "¿Quién es EMP-0004?" with the request id "client-1"
    Then the response status is 200
    And the events "request", "agent_run" and "audit" for "client-1" name the client "test-suite"
    And the log does not contain the key of "test-suite"

  Scenario: A client over the limit gets 429 while another client still passes
    Given the secured HR assistant is running with a limit of 2 requests per minute
    When the client "test-suite" asks "Hola" 3 times
    Then the last response is 429 with the detail "rate limit exceeded"
    And the last response says to retry after 60 seconds
    And the client "other-team" can still ask "Hola"

  Scenario: The limit frees up once the minute has passed
    Given the secured HR assistant is running with a limit of 1 requests per minute
    When the client "test-suite" asks "Hola" 2 times
    And 61 seconds pass
    And the client "test-suite" asks "Hola" 1 times
    Then the last response status is 200

  Scenario: Production refuses to start with the fake model and no keys
    When the product starts in production with the fake model and no API keys
    Then startup fails naming "MODEL_PROVIDER" and "API_KEYS"

  Scenario: Production starts with safe settings
    When the product starts in production with the gateway, long keys and hidden traces
    Then startup succeeds in the production environment

  Scenario: Malformed API keys stop startup without revealing the key
    When the product starts with API_KEYS "acme:good-key-1234567,secret-value-without-client"
    Then startup fails naming "API_KEYS", entry 2 and length 27
    And the startup error does not contain "secret-value-without-client"
