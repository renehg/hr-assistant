"""Pruebas del bucle del agente con un modelo de guion inyectado."""

import copy
import io
import json
from datetime import datetime, timezone

import pytest

from app.agent import Agent, Tool
from app.clock import FixedClock
from app.config import load_settings
from app.llm import Completion
from app.logging_json import JsonLogger
from app.pricing import PriceTable
from app.router import Route

CAP_MESSAGE = "No pude completar la respuesta. Intenta con una pregunta más concreta."
TOOL_PREFIX = "Resultado de la herramienta: "


class ScriptedModel:
    """Modelo de prueba que devuelve respuestas fijas y guarda lo que recibe."""

    def __init__(self, texts, input_tokens=1, output_tokens=1):
        self._texts = list(texts)
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.calls = []

    def complete(self, messages):
        """Devuelve la siguiente respuesta del guion (repite la última)."""
        self.calls.append(copy.deepcopy(list(messages)))
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        return Completion(text, self._input_tokens, self._output_tokens)


class CompletionModel:  # pylint: disable=too-few-public-methods
    """Modelo de prueba que devuelve objetos ``Completion`` ya armados, en orden."""

    def __init__(self, completions):
        self._completions = list(completions)

    def complete(self, messages):  # pylint: disable=unused-argument
        """Devuelve la siguiente respuesta de la lista."""
        return self._completions.pop(0)


def _tool(name, **args):
    return json.dumps({"tool": name, "args": args})


def _answer(text):
    return json.dumps({"answer": text})


def test_tool_result_is_sent_back_and_tokens_are_summed(directory):
    model = ScriptedModel(
        [_tool("get_employee", employee_id="EMP-0001"), _answer("listo")],
        input_tokens=10,
        output_tokens=2,
    )
    result = Agent(model=model, directory=directory, max_steps=3).run("EMP-0001", [])
    assert result.answer == "listo"
    assert result.steps == 2
    assert result.tools_used == ["get_employee"]
    assert (result.input_tokens, result.output_tokens) == (20, 4)
    last_message = model.calls[1][-1]
    assert last_message["role"] == "user"
    assert last_message["content"].startswith(TOOL_PREFIX)
    assert "Ana López" in last_message["content"]


def test_history_is_sent_before_the_question(directory):
    model = ScriptedModel([_answer("hola")])
    history = [{"role": "user", "content": "Hola"}]
    Agent(model=model, directory=directory, max_steps=3).run("¿Y EMP-0002?", history)
    messages = model.calls[0]
    assert messages[0]["content"] == "Hola"
    assert messages[-1] == {"role": "user", "content": "¿Y EMP-0002?"}


def test_invalid_json_from_model_ends_with_step_cap_message(directory):
    model = ScriptedModel(["this is not json"])
    result = Agent(model=model, directory=directory, max_steps=3).run("hola", [])
    assert result.answer == CAP_MESSAGE
    assert result.steps == 3


def test_unknown_tool_does_not_raise(directory):
    model = ScriptedModel([_tool("delete_everyone")])
    result = Agent(model=model, directory=directory, max_steps=2).run("hola", [])
    assert result.answer == CAP_MESSAGE
    assert result.steps == 2


def _observed_agent(model, directory, max_steps):
    """Crea un agente cuyo logger escribe en memoria."""
    stream = io.StringIO()
    clock = FixedClock(datetime(2026, 1, 15, tzinfo=timezone.utc))
    logger = JsonLogger(service="hr-assistant", clock=clock, stream=stream)
    agent = Agent(model=model, directory=directory, max_steps=max_steps, logger=logger)
    return agent, stream


def _events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_each_tool_call_is_audited_and_the_run_is_summarized(directory):
    model = ScriptedModel(
        [_tool("search_by_department", department="Tecnología"), _answer("listo")],
        input_tokens=7,
        output_tokens=2,
    )
    agent, stream = _observed_agent(model, directory, max_steps=3)
    history = [{"role": "user", "content": "Hola"}]

    agent.run("¿Quiénes están en Tecnología?", history, request_id="req-7")

    audit, run = _events(stream)
    assert audit["event"] == "audit"
    assert audit["request_id"] == "req-7"
    assert audit["action"] == "tool_call"
    assert audit["tool"] == "search_by_department"
    assert audit["args"] == {"department": "Tecnología"}
    assert run["event"] == "agent_run"
    assert run["request_id"] == "req-7"
    assert run["question_chars"] == len("¿Quiénes están en Tecnología?")
    assert run["history_messages"] == 1
    assert run["steps"] == 2
    assert run["tools"] == ["search_by_department"]
    assert (run["input_tokens"], run["output_tokens"]) == (14, 4)
    assert run["stopped"] == "answer"


def test_step_cap_is_reported_and_an_invalid_tool_is_not_audited(directory):
    model = ScriptedModel([_tool("delete_everyone")])
    agent, stream = _observed_agent(model, directory, max_steps=2)

    agent.run("hola", [], request_id="req-8")

    events = _events(stream)
    assert [event["event"] for event in events] == ["agent_run"]
    assert events[0]["stopped"] == "step_cap"
    assert events[0]["tools"] == []


# Sesión 3: modelo por corrida, ventana de historial y costo.

SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
HISTORY = [
    {"role": ("user", "assistant")[index % 2], "content": f"mensaje {index}"}
    for index in range(4)
]


def _prices():
    """Precios reales del producto."""
    return PriceTable.from_file(load_settings({}).prices_path)


def _small_route():
    return Route(model=SMALL_MODEL, reason="default")


def test_model_given_per_run_is_used_and_a_cached_call_costs_nothing(directory):
    unused = ScriptedModel([_answer("no debería usarse")])
    model = CompletionModel(
        [
            Completion(_tool("get_employee", employee_id="EMP-0001"), 1000, 100),
            Completion(_answer("listo"), 2000, 50, cached=True),
        ]
    )
    agent = Agent(model=unused, directory=directory, max_steps=3, prices=_prices())

    result = agent.run("EMP-0001", [], model=model, route=_small_route())

    assert not unused.calls
    assert result.answer == "listo"
    assert (result.model, result.route) == (SMALL_MODEL, "default")
    assert result.cached_calls == 1
    assert result.cost_usd == pytest.approx((1000 * 0.045 + 100 * 0.384) / 1e6)


@pytest.mark.parametrize(("window", "kept"), [(0, 0), (2, 2), (10, 4)])
def test_history_window_keeps_only_the_last_messages(directory, window, kept):
    model = ScriptedModel([_answer("hola")])
    agent = Agent(
        model=model,
        directory=directory,
        max_steps=3,
        prices=_prices(),
        history_window=window,
    )

    agent.run("¿Y EMP-0002?", HISTORY, model=model, route=_small_route())

    sent = model.calls[0]
    assert sent[:-1] == HISTORY[len(HISTORY) - kept:]
    assert sent[-1] == {"role": "user", "content": "¿Y EMP-0002?"}


def test_agent_run_event_reports_model_route_and_cost_without_texts(directory):
    model = ScriptedModel([_answer("Respuesta privada")], input_tokens=10)
    stream = io.StringIO()
    clock = FixedClock(datetime(2026, 1, 15, tzinfo=timezone.utc))
    logger = JsonLogger(service="hr-assistant", clock=clock, stream=stream)
    agent = Agent(
        model=model, directory=directory, max_steps=3, logger=logger, prices=_prices()
    )

    result = agent.run(
        "Pregunta privada", [], "req-9", model=model, route=_small_route()
    )

    (run,) = _events(stream)
    assert run["model"] == SMALL_MODEL
    assert run["route"] == "default"
    assert run["cached_calls"] == 0
    assert run["cost_usd"] == pytest.approx(result.cost_usd)
    assert run["cost_usd"] > 0
    assert "privada" not in stream.getvalue()


# Reto de facturación: herramientas inyectadas y mensaje de sistema propio.


def _echo_tool():
    """Herramienta de prueba que repite su argumento."""
    return Tool(
        name="echo",
        parse_args=lambda args: args if isinstance(args, dict) else None,
        run=lambda text: f"eco {text}",
        audit_args=lambda args: {},
        missing_message="error: echo necesita argumentos.",
    )


def test_system_prompt_goes_before_history_and_question(directory):
    model = ScriptedModel([_answer("hola")])
    history = [{"role": "user", "content": "Hola"}]
    agent = Agent(
        model=model, directory=directory, max_steps=3, system_prompt="[factura] reglas"
    )

    agent.run("Factura a Ferretería López", history)

    assert model.calls[0] == [
        {"role": "system", "content": "[factura] reglas"},
        {"role": "user", "content": "Hola"},
        {"role": "user", "content": "Factura a Ferretería López"},
    ]


def test_hr_agent_sends_no_system_message_and_keeps_its_tools(directory):
    model = ScriptedModel(
        [_tool("get_employee", employee_id="EMP-0001"), _answer("listo")]
    )

    result = Agent(model=model, directory=directory, max_steps=3).run("EMP-0001", [])

    assert all(message["role"] != "system" for message in model.calls[0])
    assert result.tools_used == ["get_employee"]


def test_given_tools_replace_the_directory_tools(directory):
    model = ScriptedModel(
        [
            _tool("get_employee", employee_id="EMP-0001"),
            _tool("echo", text="hola"),
            _answer("listo"),
        ]
    )
    agent = Agent(model=model, directory=directory, max_steps=3, tools=[_echo_tool()])

    result = agent.run("EMP-0001", [])

    assert result.tools_used == ["echo"]
    assert "no existe" in model.calls[1][-1]["content"]
    assert "Ana López" not in json.dumps(model.calls, ensure_ascii=False)
    assert model.calls[2][-1]["content"] == TOOL_PREFIX + "eco hola"


def test_agent_without_directory_or_tools_is_rejected():
    with pytest.raises(ValueError):
        Agent(model=ScriptedModel([_answer("hola")]), directory=None, max_steps=3)
