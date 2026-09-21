"""DiscoveryAgent 及其 Agent-as-Tool 适配器。"""

import json
from collections.abc import Sequence
from typing import Annotated, Any, Protocol

from langchain.agents import create_agent
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

Your responsibility is to discover scientific resources required by the delegated request,
including papers, repositories, datasets, and models.

Use the available resource discovery tools to find the resources needed for the request. Decide
which tools to use, what to search for, whether additional searches are necessary, and when enough
information has been collected.

Before finishing, account for every resource category explicitly requested by the delegation unless
that resource is already listed as confirmed. When a tool returns a resource that satisfies the
delegated request, include that resource in discovered_resources using only metadata supported by
the tool result. Return an empty discovered_resources list only when no new requested resource was
found. A delegation that explicitly requests both a paper and a repository is not complete until
both categories have been found or the available tools have returned no matching resource.

Return only resources discovered during this invocation. Do not repeat resources that were already
confirmed before this invocation.

Do not analyze scientific methodology, design experiments, construct experiment specifications,
execute commands, or determine whether scientific reproduction succeeded.

Never invent resources or resource metadata that are not supported by tool results.
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


def build_discovery_agent(
    *,
    model: BaseChatModel,
    discovery_tools: Sequence[BaseTool],
    context_schema: type | None = None,
):
    """构造真实 Discovery LLM Agent；具体资源发现工具由外部注入。"""
    if not discovery_tools:
        raise ValueError("DiscoveryAgent 至少需要一个 resource discovery tool")
    return create_agent(
        model=model,
        tools=list(discovery_tools),
        system_prompt=DISCOVERY_SYSTEM_PROMPT,
        response_format=ToolStrategy(DiscoveryResult),
        context_schema=context_schema,
        name="discovery_agent",
    )


def _merge_resources(
    current: list[ResearchResource], discovered: list[ResearchResource]
) -> list[ResearchResource]:
    """按稳定资源 ID 合并本轮发现结果，避免父 State 中出现重复资源。"""
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

        Use this specialist to discover external scientific resources, including
        papers, repositories, datasets, and models. This specialist does not
        design experiments, execute commands, or determine whether a reproduction
        attempt succeeded.
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

        current_resources = _merge_resources(parent["resources"], result.discovered_resources)
        observation = {
            "action": "discovery_result",
            "summary": result.summary.model_dump(mode="json"),
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
