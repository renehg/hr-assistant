"""Agente único con bucle con tope y dos herramientas de solo lectura."""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.directory import EmployeeDirectory
from app.llm import TOOL_RESULT_PREFIX, Completion, LanguageModel
from app.logging_json import JsonLogger
from app.pricing import PriceTable
from app.router import Route

STEP_CAP_MESSAGE = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)
INVALID_FORMAT_MESSAGE = (
    'Formato inválido: responde un único objeto JSON con "tool" y "args" '
    'o con "answer".'
)
STOPPED_ANSWER = "answer"
STOPPED_STEP_CAP = "step_cap"

Tracer = Callable[[str, str], Callable[[Callable[..., Any]], Callable[..., Any]]]


def no_tracing(_name: str, _run_type: str) -> Callable[[Callable], Callable]:
    """Fábrica de decoradores nulos, para cuando no hay trazas.

    :param _name: Nombre de la traza (sin uso).
    :type _name: str
    :param _run_type: Tipo de corrida (sin uso).
    :type _run_type: str
    :return: Un decorador que devuelve la misma función.
    :rtype: Callable
    """
    return lambda function: function


@dataclass
class AgentResult:  # pylint: disable=too-many-instance-attributes
    """Resultado de una ejecución del agente.

    :param answer: Respuesta final en español.
    :type answer: str
    :param steps: Vueltas del bucle usadas.
    :type steps: int
    :param tools_used: Nombres de las herramientas ejecutadas, en orden.
    :type tools_used: list[str]
    :param input_tokens: Suma de tokens de entrada.
    :type input_tokens: int
    :param output_tokens: Suma de tokens de salida.
    :type output_tokens: int
    :param stopped: Por qué terminó: ``answer`` o ``step_cap``.
    :type stopped: str
    :param model: Nombre del modelo usado en todas las vueltas.
    :type model: str
    :param route: Motivo del enrutador para elegir ese modelo.
    :type route: str
    :param cached_calls: Llamadas servidas desde la caché del gateway.
    :type cached_calls: int
    :param cost_usd: Costo de la corrida en USD, sin redondear.
    :type cost_usd: float
    """

    answer: str
    steps: int = 0
    tools_used: List[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stopped: str = STOPPED_STEP_CAP
    model: str = ""
    route: str = ""
    cached_calls: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class _RunModel:
    """Modelo de una corrida junto con la ruta que lo eligió.

    :param model: Modelo que responde todas las vueltas.
    :type model: LanguageModel
    :param route: Nombre del modelo (para el costo) y motivo del enrutador.
    :type route: Route
    """

    model: LanguageModel
    route: Route


@dataclass(frozen=True)
class _Caller:
    """Quién hizo la petición, para unir los eventos del log.

    :param request_id: Id de la petición.
    :type request_id: str or None
    :param client: Nombre del cliente autenticado (nunca su clave).
    :type client: str or None
    """

    request_id: Optional[str]
    client: Optional[str]


def _parse_reply(text: str) -> Optional[dict]:
    """Interpreta la respuesta del modelo según el protocolo.

    :param text: Texto devuelto por el modelo.
    :type text: str
    :return: El objeto si es válido (``answer`` o ``tool``), si no ``None``.
    :rtype: dict or None
    """
    try:
        reply = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(reply, dict):
        return None
    if isinstance(reply.get("answer"), str):
        return reply
    if isinstance(reply.get("tool"), str):
        return reply
    return None


class Agent:  # pylint: disable=too-many-instance-attributes
    """Agente sin estado: cada llamada a ``run`` es independiente.

    :param model: Modelo que cumple la interfaz ``complete(messages)``.
    :type model: LanguageModel
    :param directory: Directorio de empleados de solo lectura.
    :type directory: EmployeeDirectory
    :param max_steps: Tope de vueltas del bucle (mínimo 1).
    :type max_steps: int
    :param logger: Logger JSON para ``audit`` y ``agent_run``; ``None`` no
        registra nada.
    :type logger: JsonLogger or None
    :param tracer: Fábrica de decoradores de traza ``(nombre, tipo)``.
    :type tracer: Callable or None
    :param prices: Tabla de precios; ``None`` deja el costo en 0.
    :type prices: PriceTable or None
    :param history_window: Mensajes de historial que se mandan al modelo;
        ``None`` manda todo el historial.
    :type history_window: int or None
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        model: LanguageModel,
        directory: EmployeeDirectory,
        max_steps: int,
        *,
        logger: Optional[JsonLogger] = None,
        tracer: Optional[Tracer] = None,
        prices: Optional[PriceTable] = None,
        history_window: Optional[int] = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if history_window is not None and history_window < 0:
            raise ValueError("history_window must be at least 0")
        self._trace = tracer or no_tracing
        self._model = model
        self._directory = directory
        self._max_steps = max_steps
        self._logger = logger
        self._prices = prices
        self._history_window = history_window
        self._loop = self._trace("agent.run", "chain")(self._run_loop)
        trace = self._trace
        self._tools: Dict[str, Tuple[str, Callable[[str], str]]] = {
            "get_employee": (
                "employee_id",
                trace("get_employee", "tool")(self._get_employee),
            ),
            "search_by_department": (
                "department",
                trace("search_by_department", "tool")(self._search_by_department),
            ),
        }

    def run(  # pylint: disable=too-many-arguments
        self,
        question: str,
        history: Sequence[Mapping[str, str]],
        request_id: Optional[str] = None,
        *,
        model: Optional[LanguageModel] = None,
        route: Optional[Route] = None,
        client: Optional[str] = None,
    ) -> AgentResult:
        """Responde una pregunta usando el bucle con tope.

        Todas las vueltas usan el mismo modelo. Al terminar registra
        ``agent_run`` solo con conteos, modelo, ruta, costo y cliente, nunca
        con textos.

        :param question: Pregunta de la persona.
        :type question: str
        :param history: Conversación previa enviada por el cliente.
        :type history: Sequence[Mapping[str, str]]
        :param request_id: Id de la petición, para unir los eventos del log.
        :type request_id: str or None
        :param model: Modelo de esta corrida; ``None`` usa el del constructor.
        :type model: LanguageModel or None
        :param route: Modelo y motivo elegidos por el enrutador; su nombre se
            usa para el costo.
        :type route: Route or None
        :param client: Nombre del cliente autenticado, para ``audit`` y
            ``agent_run``.
        :type client: str or None
        :return: Respuesta, vueltas, herramientas, tokens, costo y motivo de
            parada.
        :rtype: AgentResult
        """
        chosen = model or self._model
        if route is None:
            route = Route(model=str(getattr(chosen, "name", "")), reason="")
        run_model = _RunModel(model=chosen, route=route)
        caller = _Caller(request_id=request_id, client=client)
        result = self._loop(question, self._windowed(history), caller, run_model)
        if self._logger is not None:
            self._logger.emit(
                "agent_run",
                request_id,
                client=client,
                question_chars=len(question),
                history_messages=len(history),
                steps=result.steps,
                tools=list(result.tools_used),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                stopped=result.stopped,
                model=result.model,
                route=result.route,
                cached_calls=result.cached_calls,
                cost_usd=result.cost_usd,
            )
        return result

    def _windowed(
        self, history: Sequence[Mapping[str, str]]
    ) -> Sequence[Mapping[str, str]]:
        """Recorta el historial a los últimos ``history_window`` mensajes.

        :param history: Conversación previa enviada por el cliente.
        :type history: Sequence[Mapping[str, str]]
        :return: Los mensajes que se mandan al modelo.
        :rtype: Sequence[Mapping[str, str]]
        """
        if self._history_window is None:
            return history
        if self._history_window == 0:
            return []
        return history[-self._history_window:]

    def _call_cost(self, model_name: str, completion: Completion) -> float:
        """Calcula el costo de una llamada; si salió de la caché no cuesta.

        :param model_name: Nombre del modelo usado.
        :type model_name: str
        :param completion: Respuesta del modelo.
        :type completion: Completion
        :return: Costo en USD.
        :rtype: float
        """
        if completion.cached or self._prices is None:
            return 0.0
        return self._prices.cost_usd(
            model_name, completion.input_tokens, completion.output_tokens
        )

    def _run_loop(
        self,
        question: str,
        history: Sequence[Mapping[str, str]],
        caller: _Caller,
        run_model: _RunModel,
    ) -> AgentResult:
        """Bucle con tope: pide al modelo, ejecuta herramientas y repite.

        :param question: Pregunta de la persona.
        :type question: str
        :param history: Historial ya recortado por la ventana.
        :type history: Sequence[Mapping[str, str]]
        :param caller: Petición y cliente, para los eventos ``audit``.
        :type caller: _Caller
        :param run_model: Modelo y ruta de esta corrida.
        :type run_model: _RunModel
        :return: Respuesta, vueltas, herramientas, tokens, costo y motivo de
            parada.
        :rtype: AgentResult
        """
        complete = self._trace("model.complete", "llm")(run_model.model.complete)
        messages = [
            {"role": str(item["role"]), "content": str(item["content"])}
            for item in history
        ]
        messages.append({"role": "user", "content": question})
        result = AgentResult(
            answer=STEP_CAP_MESSAGE,
            model=run_model.route.model,
            route=run_model.route.reason,
        )
        while result.steps < self._max_steps:
            completion = complete(messages)
            result.steps += 1
            result.input_tokens += completion.input_tokens
            result.output_tokens += completion.output_tokens
            result.cached_calls += int(completion.cached)
            result.cost_usd += self._call_cost(result.model, completion)
            reply = _parse_reply(completion.text)
            messages.append({"role": "assistant", "content": completion.text})
            if reply is None:
                messages.append({"role": "user", "content": INVALID_FORMAT_MESSAGE})
                continue
            if "answer" in reply and isinstance(reply["answer"], str):
                result.answer = reply["answer"]
                result.stopped = STOPPED_ANSWER
                return result
            tool_output = self._run_tool(
                reply["tool"], reply.get("args"), result, caller
            )
            messages.append(
                {"role": "user", "content": TOOL_RESULT_PREFIX + tool_output}
            )
        result.answer = STEP_CAP_MESSAGE
        result.stopped = STOPPED_STEP_CAP
        return result

    def _run_tool(
        self,
        name: str,
        args: object,
        result: AgentResult,
        caller: _Caller,
    ) -> str:
        """Ejecuta una herramienta; los errores se devuelven como texto.

        Solo las llamadas válidas dejan un evento ``audit``, con el argumento
        ya validado (un id o un departamento, nunca texto libre) y el cliente.

        :param name: Nombre de la herramienta pedida.
        :type name: str
        :param args: Argumentos pedidos por el modelo.
        :type args: object
        :param result: Resultado en curso, para registrar la herramienta usada.
        :type result: AgentResult
        :param caller: Petición y cliente en curso.
        :type caller: _Caller
        :return: Texto con el resultado o con el error.
        :rtype: str
        """
        if name not in self._tools:
            return f"error: la herramienta {name!r} no existe."
        arg_name, function = self._tools[name]
        if not isinstance(args, dict) or not isinstance(args.get(arg_name), str):
            return f"error: falta el argumento {arg_name!r} para {name}."
        result.tools_used.append(name)
        if self._logger is not None:
            self._logger.emit(
                "audit",
                caller.request_id,
                client=caller.client,
                action="tool_call",
                tool=name,
                args={arg_name: args[arg_name]},
            )
        return function(args[arg_name])

    def _get_employee(self, employee_id: str) -> str:
        """Herramienta ``get_employee``.

        :param employee_id: Id del empleado.
        :type employee_id: str
        :return: Datos del empleado en JSON o un aviso de que no existe.
        :rtype: str
        """
        employee = self._directory.get_employee(employee_id)
        if employee is None:
            return f"El empleado {employee_id} no existe."
        return json.dumps(employee, ensure_ascii=False)

    def _search_by_department(self, department: str) -> str:
        """Herramienta ``search_by_department``.

        :param department: Nombre del departamento.
        :type department: str
        :return: Lista de empleados en JSON o un aviso si no hay ninguno.
        :rtype: str
        """
        employees = self._directory.search_by_department(department)
        if not employees:
            return f"No hay empleados en el departamento {department}."
        return json.dumps(employees, ensure_ascii=False)
