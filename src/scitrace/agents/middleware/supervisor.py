"""SciTrace Supervisor 使用的编排中间件。"""

import json
from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.messages import SystemMessage


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
    """把 Main State 当前业务事实呈现给 Supervisor，不给出路由建议。"""

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
