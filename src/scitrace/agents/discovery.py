"""DiscoveryAgent 及其 Agent-as-Tool 适配器。"""

import json
from ast import literal_eval
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Protocol

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.types import Command

from scitrace.agents.state import SciTraceState
from scitrace.models import ResearchResource
from scitrace.models.agent_results import DiscoveryResult

DISCOVERY_SYSTEM_PROMPT = """You are the Discovery specialist in a scientific reproduction system.
Your responsibility is resource identity: discover and verify the correct papers, repositories,
datasets, and models required by the delegated request.

Search tools return unverified candidates. A search candidate is not a confirmed ResearchResource.
You must inspect a candidate before including it in DiscoveryResult. Use inspect tools to verify its
identity, metadata, location, and relationship to the request. Continue searching or inspecting when
the available evidence is insufficient. Do not design experiments, execute commands, or decide
whether scientific reproduction succeeded.

Return only newly confirmed resources. Do not repeat resources that were already confirmed before
this invocation. Never invent a resource or promote an uninspected candidate.
"""


class DiscoveryAgent(Protocol):
    """Discovery compiled graph 使用的最小调用协议。"""

    def invoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        context: Any = None,
    ) -> dict[str, Any]: ...


class DiscoveryInspectionMiddleware(AgentMiddleware):
    """Search 产生未验证 candidate 后，强制下一步使用对应 inspect tool。"""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        required_tool = self._required_inspection_tool(request.messages)
        if required_tool is None:
            return handler(request)
        tools = [candidate for candidate in request.tools if candidate.name == required_tool]
        if len(tools) != 1:
            raise RuntimeError(f"找不到 candidate 要求的 inspect tool：{required_tool}")
        return handler(
            request.override(
                tools=tools,
                tool_choice=required_tool,
                response_format=None,
            )
        )

    @staticmethod
    def _required_inspection_tool(messages: list[Any]) -> str | None:
        if not messages or not isinstance(messages[-1], ToolMessage):
            return None
        message = messages[-1]
        if not (message.name or "").startswith("search_"):
            return None
        try:
            candidates = json.loads(str(message.content))
        except json.JSONDecodeError:
            try:
                candidates = literal_eval(str(message.content))
            except (SyntaxError, ValueError):
                return None
        if not isinstance(candidates, list):
            return None
        required = {
            candidate.get("required_inspection_tool")
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("required_inspection_tool")
        }
        return next(iter(required)) if len(required) == 1 else None


def _inspected_resource_ids(messages: list[Any]) -> set[str]:
    """提取本轮 inspect tools 实际确认过的 ResearchResource ID。"""
    inspected: set[str] = set()
    for message in messages:
        if not isinstance(message, ToolMessage) or not (message.name or "").startswith("inspect_"):
            continue
        try:
            value = json.loads(str(message.content))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            inspected.add(value["id"])
    return inspected


def build_discovery_agent(
    *,
    model: BaseChatModel,
    discovery_tools: Sequence[BaseTool],
    context_schema: type | None = None,
):
    """构造真实 Discovery LLM Agent；具体 provider tools 由外部注入。"""
    if not discovery_tools:
        raise ValueError("DiscoveryAgent 至少需要一个 search/inspect tool")
    return create_agent(
        model=model,
        tools=list(discovery_tools),
        middleware=[DiscoveryInspectionMiddleware()],
        system_prompt=DISCOVERY_SYSTEM_PROMPT,
        response_format=ToolStrategy(DiscoveryResult),
        context_schema=context_schema,
        name="discovery_agent",
    )


def _merge_resources(
    current: list[ResearchResource], discovered: list[ResearchResource]
) -> list[ResearchResource]:
    by_id = {resource.id: resource for resource in current}
    by_id.update({resource.id: resource for resource in discovered})
    return list(by_id.values())


def build_discovery_agent_tool(discovery_agent: DiscoveryAgent) -> BaseTool:
    """把真实 DiscoveryAgent 包装为可更新 SciTraceState 的 Tool。"""

    @tool("discovery_agent")
    def discovery_agent_tool(
        request: str,
        runtime: ToolRuntime[Any, SciTraceState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Delegate scientific resource discovery to the Discovery specialist.

        Use this specialist to discover and verify external scientific resources,
        including papers, repositories, datasets, and models. This specialist does
        not design experiments, execute commands, or determine whether a
        reproduction attempt succeeded.
        """
        parent = runtime.state
        confirmed = [
            {"id": resource.id, "kind": resource.kind, "name": resource.name}
            for resource in parent["resources"]
        ]
        instruction = (
            f"Delegated request:\n{request}\n\n"
            "Resources already confirmed before this invocation:\n"
            f"{json.dumps(confirmed, ensure_ascii=False)}"
        )
        child_result = discovery_agent.invoke(
            {"messages": [HumanMessage(content=instruction)]},
            context=runtime.context,
        )
        result = child_result.get("structured_response")
        if not isinstance(result, DiscoveryResult):
            raise RuntimeError("DiscoveryAgent 未返回合法的 DiscoveryResult")
        inspected_ids = _inspected_resource_ids(child_result.get("messages", []))
        uninspected_ids = {
            resource.id for resource in result.discovered_resources if resource.id not in inspected_ids
        }
        if uninspected_ids:
            ids = ", ".join(sorted(uninspected_ids))
            raise RuntimeError(f"DiscoveryAgent 返回了未经 inspect 确认的资源：{ids}")

        current_resources = _merge_resources(parent["resources"], result.discovered_resources)
        observation = {
            "action": "discovery_result",
            "newly_discovered": result.summary.model_dump(mode="json"),
            "confirmed_resources": [
                {"kind": resource.kind, "name": resource.name}
                for resource in current_resources
            ],
        }
        return Command(
            update={
                "resources": current_resources,
                "required_specialist": None,
                "messages": [
                    ToolMessage(
                        tool_call_id=tool_call_id,
                        content=json.dumps(observation, ensure_ascii=False),
                    )
                ],
            }
        )

    return discovery_agent_tool
