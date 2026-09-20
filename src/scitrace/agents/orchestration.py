"""SciTrace Supervisor 的生产编排内核。"""

import json
from collections.abc import Callable, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from scitrace.agents.state import SciTraceState


class SpecialistRoutingMiddleware(AgentMiddleware):
    """有明确路由义务时，只暴露并强制调用对应 Specialist tool。"""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        required = request.state.get("required_specialist")
        if required is None:
            return handler(request)
        expected_name = f"{required}_agent"
        tools = [candidate for candidate in request.tools if candidate.name == expected_name]
        if len(tools) != 1:
            raise RuntimeError(f"找不到 required specialist tool：{expected_name}")
        return handler(request.override(tools=tools, tool_choice=expected_name))


class StateContextMiddleware(AgentMiddleware):
    """把 Main State 的当前业务事实呈现给 Supervisor，不给出路由建议。"""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        state = request.state
        snapshot = {
            "task_id": state.get("task_id"),
            "resources": [resource.model_dump(mode="json") for resource in state.get("resources", [])],
            "experiment_spec": (
                state["experiment_spec"].model_dump(mode="json")
                if state.get("experiment_spec") is not None
                else None
            ),
            "experiment_run": (
                state["experiment_run"].model_dump(mode="json")
                if state.get("experiment_run") is not None
                else None
            ),
            "required_specialist": state.get("required_specialist"),
            "final_answer": state.get("final_answer"),
        }
        base_prompt = str(request.system_message.content) if request.system_message else ""
        state_prompt = (
            f"{base_prompt}\n\nCurrent SciTraceState (authoritative facts, not routing advice):\n"
            f"{json.dumps(snapshot, ensure_ascii=False)}"
        )
        return handler(request.override(system_message=SystemMessage(content=state_prompt)))


SCITRACE_SYSTEM_PROMPT = """You are SciTraceAgent, the supervisor of a scientific reproduction system.
Your goal is to resolve the user's scientific reproduction request by coordinating the available
specialist agents. Use the available specialists according to the current task state and accumulated
evidence. A specialist may be called multiple times when necessary.
Do not invent scientific resources, experiment results, or missing evidence.
A successful program execution alone is not sufficient evidence that a scientific result has been
reproduced. When the user's scientific goal has been resolved with sufficient evidence, provide the
final answer and stop.
"""


def _default_checkpointer() -> InMemorySaver:
    """构造允许 SciTrace 领域模型安全反序列化的内存 checkpointer。"""
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("scitrace.models.resource", "PaperResource"),
            ("scitrace.models.resource", "RepositoryResource"),
            ("scitrace.models.experiment", "ExperimentSpec"),
            ("scitrace.models.execution", "ExperimentRun"),
            ("scitrace.models.execution", "MetricOutput"),
        ]
    )
    return InMemorySaver(serde=serde)


def build_scitrace_agent(
    *,
    model: BaseChatModel,
    specialist_tools: Sequence[BaseTool],
    context_schema: type | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """构造生产编排图；模型与 Specialist tools 必须由 composition root 注入。"""
    if not specialist_tools:
        raise ValueError("SciTraceAgent 至少需要一个 Specialist tool")
    return create_agent(
        model=model,
        tools=list(specialist_tools),
        middleware=[StateContextMiddleware(), SpecialistRoutingMiddleware()],
        state_schema=SciTraceState,
        context_schema=context_schema,
        checkpointer=checkpointer or _default_checkpointer(),
        system_prompt=SCITRACE_SYSTEM_PROMPT,
        name="scitrace_agent",
    )


def initial_scitrace_state(task_id: str, query: str) -> SciTraceState:
    """创建一次 SciTraceAgent 调用所需的最小主状态。"""
    return {
        "messages": [HumanMessage(content=query)],
        "task_id": task_id,
        "resources": [],
        "experiment_spec": None,
        "experiment_run": None,
        "required_specialist": None,
        "final_answer": None,
    }
