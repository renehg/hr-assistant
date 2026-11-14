Feature: Trace and measure every request
  Support must be able to answer "what happened with request X" using the
  request id, the JSON log and the process metrics.

  Scenario: A request without an id gets a generated UUID
    Given the observed HR assistant is running
    When I check the health of the service
    Then the response carries a generated UUID request id

  Scenario: The client request id is kept in the header and the body
    Given the observed HR assistant is running
    When I ask "¿Quién es EMP-0004?" with the request id "demo-123"
    Then the response header request id is "demo-123"
    And the response body request id is "demo-123"

  Scenario: A question leaves request, agent_run and audit events with the same id
    Given the observed HR assistant is running
    When I ask "¿Quién es EMP-0004?" with the request id "trace-42"
    Then the log has the events "request", "agent_run" and "audit" for "trace-42"
    And the audit event records the tool "get_employee" with its arguments

  Scenario: The agent_run event never contains the question or the answer
    Given the observed HR assistant is running
    When I ask "¿Quién es EMP-0004?" with the request id "private-1"
    Then the log does not contain the question or the answer

  Scenario: An internal error returns a generic 500 with the request id
    Given the observed HR assistant is running with a broken model
    When I ask "¿Quién es EMP-0004?" with the request id "boom-1"
    Then the response is a generic internal error for "boom-1"
    And the log has an error event of type "RuntimeError" without its message

  Scenario: Metrics report requests, tokens and a met SLO
    Given the observed HR assistant is running
    When I ask "¿Quién es EMP-0004?" with the request id "fast-1"
    And I read the metrics
    Then the metrics count 1 request
    And the metrics tokens match the answer tokens
    And the SLO target is 2000 ms and it is met

  Scenario: Metrics report a missed SLO when requests are slow
    Given the observed HR assistant is running with requests that take 3 seconds
    When I ask "¿Quién es EMP-0004?" with the request id "slow-1"
    And I read the metrics
    Then the SLO is not met

  Scenario: The home page shows the request id
    Given the observed HR assistant is running
    When I open the home page
    Then the page has a place for the request id

  Scenario: An unsafe client request id never reaches the log
    Given the observed HR assistant is running
    When I check the health of the service with a request id of 129 characters
    Then the response carries a generated UUID request id
    And the log uses the generated request id instead of the unsafe one

  Scenario: A rejected question still carries a request id and is logged
    Given the observed HR assistant is running
    When I ask an empty question
    Then the response status is 422
    And the response carries a generated UUID request id
    And the log has a request event with status 422 for that request id

  Scenario: Metrics report errors after an internal error
    Given the observed HR assistant is running with a broken model
    When I ask "¿Quién es EMP-0004?" with the request id "boom-2"
    And I read the metrics
    Then the metrics error rate is above 0

  Scenario: Tracing turned on without an API key changes nothing
    Given the observed HR assistant is running with tracing on and no API key
    When I ask "¿Quién es EMP-0004?" with the request id "no-key-1"
    Then the response body request id is "no-key-1"
    And the answer mentions "Jorge Díaz"
