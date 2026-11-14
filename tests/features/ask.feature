Feature: Ask the HR assistant about employees
  HR staff ask questions and the single agent answers using read-only tools.

  Scenario: Asking for an employee by id uses get_employee
    Given the HR assistant is running
    When I ask "¿Quién es EMP-0004?"
    Then the answer mentions "Jorge Díaz"
    And the tools used are "get_employee"
    And the agent took 2 steps

  Scenario: Unknown employee is reported
    Given the HR assistant is running
    When I ask "¿Quién es EMP-9999?"
    Then the answer says the employee does not exist
    And the tools used are "get_employee"

  Scenario: Asking for a department lists its people
    Given the HR assistant is running
    When I ask "¿Quiénes trabajan en Tecnología?"
    Then the answer mentions "Ana López"
    And the answer mentions "Marta Ruiz"
    And the answer mentions "Jorge Díaz"
    And the tools used are "search_by_department"

  Scenario: A question without id or department gets the help message
    Given the HR assistant is running
    When I ask "Hola, ¿cómo estás?"
    Then the answer is "Pregúntame por un empleado (EMP-0001) o un departamento."
    And no tools were used
    And the agent took 1 steps

  Scenario: The step cap stops the loop
    Given the HR assistant is running with a step cap of 1
    When I ask "¿Quién es EMP-0004?"
    Then the answer is "No pude completar la respuesta. Intenta con una pregunta más concreta."
    And the agent took 1 steps

  Scenario Outline: Invalid questions are rejected
    Given the HR assistant is running
    When I send a question of <length> characters
    Then the request is rejected as invalid

    Examples:
      | length |
      | 0      |
      | 2001   |

  Scenario: The API keeps no state between requests
    Given the HR assistant is running
    When I ask "¿Quién es EMP-0004?" twice
    Then both responses are identical
