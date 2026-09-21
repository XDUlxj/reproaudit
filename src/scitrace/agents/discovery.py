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

from scitrace.agents.discovery_state import DiscoveryState
from scitrace.agents.middleware import ResourceDeduplicationMiddleware
from scitrace.agents.state import SciTraceState
from scitrace.models import ResearchResource
from scitrace.models.discovery import DiscoverySelection
from scitrace.services import ResourceAdmissionService, ResourceService

DISCOVERY_SYSTEM_PROMPT = """You are the Discovery specialist in a scientific reproduction system.

Your responsibility is to search for the scientific resources explicitly requested by the
delegation. You can search four resource categories: papers, repositories, datasets, and models.

Use the available resource discovery tools to find the resources needed for the request. Decide
which tools to use, what to search for, whether additional searches are necessary, and when enough
information has been collected. Every Discovery invocation must call at least one available
discovery tool before returning its final DiscoverySelection, including when the final selection is
empty.

Search results are candidates, not confirmed ResearchResources. The system automatically classifies
every search observation as new_candidates, existing_resources, or ambiguous_candidates. You decide
which Search Tools to call, whether independent searches can be called together, how to revise a
query, which NEW candidates to select, which EXISTING resources to reuse, which AMBIGUOUS candidates
to abandon, and when the delegated search is complete. Do not select AMBIGUOUS candidates.

Return a DiscoverySelection containing selected NEW candidate objects exactly as observed and IDs
of selected EXISTING resources. Your final DiscoverySelection must reference only resources
actually returned in tool observations during this invocation. For a NEW candidate, copy the
candidate object exactly as observed. Do not reconstruct, normalize, enrich, summarize, or modify
it. Copy every field and value, including locations and metadata even when they appear optional or
empty. For an EXISTING resource, return only an ID that appeared in an existing_resources
observation. You must use a discovery tool before selecting any NEW candidate; your own knowledge
is never an observation. Never create a candidate or resource ID from your own knowledge. Do not include resources already
present in the parent-confirmed list. Verification, final deduplication, and persistence happen
deterministically after your Agent Loop and are not tools available to you.

Do not analyze scientific methodology, design experiments, construct experiment specifications,
execute commands, or determine whether scientific reproduction succeeded.

Never invent resources or resource metadata that are not supported by tool results. If a search
returns no useful result, try a meaningfully different query when reasonable. Do not repeat
effectively identical searches. If reasonable alternatives are exhausted, return an empty
DiscoverySelection instead of continuing indefinitely.
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
    resource_service: ResourceService,
    context_schema: type | None = None,
):
    """构造真实 Discovery LLM Agent；具体资源发现工具由外部注入。"""
    if not discovery_tools:
        raise ValueError("DiscoveryAgent 至少需要一个 resource discovery tool")
    return create_agent(
        model=model,
        tools=list(discovery_tools),
        middleware=[
            ResourceDeduplicationMiddleware(
                resource_service,
                tool_names={tool.name for tool in discovery_tools},
            )
        ],
        system_prompt=DISCOVERY_SYSTEM_PROMPT,
        response_format=ToolStrategy(DiscoverySelection),
        state_schema=DiscoveryState,
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


def build_discovery_agent_tool(
    discovery_agent: DiscoveryAgent,
    admission_service: ResourceAdmissionService,
) -> BaseTool:
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
        ]  # 告知 Agent 当前已经确认的资源
        instruction = (
            f"Delegated request:\n{request}\n\n"
            "Resources already confirmed before this invocation:\n"
            f"{json.dumps(confirmed, ensure_ascii=False)}"
        )
        child_result = discovery_agent.invoke(
            {"messages": [HumanMessage(content=instruction)]},
            context=runtime.context,
        )
        selection = child_result.get("structured_response")  # 取 Agent 的候选选择
        if not isinstance(selection, DiscoverySelection):
            raise RuntimeError("DiscoveryAgent 未返回合法的 DiscoverySelection")
        observed_new_candidates = child_result["observed_new_candidates"]
        observed_existing_resource_ids = child_result["observed_existing_resource_ids"]
        result = admission_service.admit(
            selection,
            parent_resources=parent["resources"],
            observed_new_candidates=observed_new_candidates,
            observed_existing_resource_ids=set(observed_existing_resource_ids),
            task_id=parent["task_id"],
        )
        discovered = result.discovered_resources
        current_resources = _merge_resources(parent["resources"], discovered)
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
        )  # 更新父 State

    return discovery_agent_tool
