"""用于验证真实 Agent loop 的规则型 Tool-calling ChatModel。"""

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field


class WalkingSkeletonSupervisorModel(BaseChatModel):
    """根据已有 Tool observation 自主决定下一次 specialist delegation。"""

    available_tool_names: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def _llm_type(self) -> str:
        return "scitrace-walking-skeleton-supervisor"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"available_tool_names": self.available_tool_names}

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        names = tuple(self._tool_name(tool) for tool in tools)
        return self.model_copy(update={"available_tool_names": names})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        observations = [self._observation(message) for message in messages if isinstance(message, ToolMessage)]
        last_action = observations[-1].get("action") if observations else None

        if last_action is None:
            message = self._delegate("discovery_agent", "Find resources required for the paper reproduction.", messages)
        elif last_action == "discovery_result":
            message = self._delegate("analysis_agent", "Construct a reproducible experiment specification.", messages)
        elif last_action == "propose_spec":
            message = self._delegate("execution_agent", "Execute the accepted experiment specification.", messages)
        elif last_action == "execution_succeeded":
            message = self._delegate("analysis_agent", "Verify the observed outputs against the criterion.", messages)
        elif last_action == "goal_satisfied":
            message = AIMessage(content="Stub paper reproduction completed and its criterion was verified.")
        else:
            message = AIMessage(content=f"Unable to continue from specialist action: {last_action}")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _delegate(self, tool_name: str, request: str, messages: list[BaseMessage]) -> AIMessage:
        if tool_name not in self.available_tool_names:
            return AIMessage(content=f"Required specialist tool is unavailable: {tool_name}")
        call_id = f"call-{tool_name}-{len(messages)}"
        return AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": {"request": request}, "id": call_id}],
        )

    @staticmethod
    def _observation(message: ToolMessage) -> dict[str, Any]:
        try:
            value = json.loads(str(message.content))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _tool_name(tool: dict[str, Any] | type | Any | BaseTool) -> str:
        if isinstance(tool, BaseTool):
            return tool.name
        if isinstance(tool, dict):
            function = tool.get("function", tool)
            return str(function.get("name", ""))
        return str(getattr(tool, "__name__", getattr(tool, "name", "")))
