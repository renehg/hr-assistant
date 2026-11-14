Feature: Make every answer cheaper without making it worse
  Each answer says which model was used, why it was chosen and what it cost.
  The cost levers are routing, a history window, an output cap and the
  gateway cache.

  Scenario: A simple question goes to the small model and has a cost
    Given the HR assistant is running with the default settings
    When I ask "¿Quién es EMP-0004?"
    Then the answer used the small model with the route "default"
    And the answer cost is above 0 with 0 cached calls

  Scenario: A comparison question goes to the large model
    Given the HR assistant is running with the default settings
    When I ask "Compara a los empleados del departamento de Finanzas"
    Then the answer used the large model with the route "keyword:compara"

  Scenario Outline: The question length decides the model at the limit
    Given the HR assistant is running with the default settings
    When I ask a question of <length> characters without keywords
    Then the answer used the <size> model with the route "<route>"

    Examples:
      | length | size  | route         |
      | 80     | small | default       |
      | 81     | large | long_question |

  Scenario: With routing disabled every question goes to the large model
    Given the HR assistant is running with routing disabled
    When I ask "¿Quién es EMP-0004?"
    Then the answer used the large model with the route "routing_disabled"

  Scenario: Only the last messages of the history reach the model
    Given the HR assistant is running with a recording model and a history window of 6
    When I ask "¿Quién es EMP-0004?" after a history of 10 messages
    Then the model received only the last 6 history messages before the question

  Scenario: Metrics add up the cost of every answer
    Given the HR assistant is running with the default settings
    When I ask "¿Quién es EMP-0004?"
    And I ask "Compara a los empleados del departamento de Finanzas"
    And I read the metrics
    Then the metrics cost is the sum of the answer costs

  Scenario: A failing gateway returns 502 with the request id
    Given the HR assistant is running with a gateway that fails
    When I ask "¿Quién es EMP-0004?" with the request id "gw-down-1"
    Then the response is "model unavailable" with status 502 for "gw-down-1"

  Scenario: A cached gateway answer is counted and costs nothing
    Given the HR assistant is running with a gateway that answers from its cache
    When I ask "Hola"
    Then the answer cost is 0 with 1 cached calls
