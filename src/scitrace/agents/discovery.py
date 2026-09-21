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

from scitrace.agents.middleware import ResourceDeduplicationMiddleware
from scitrace.agents.state import SciTraceState
from scitrace.models import ResearchResource
from scitrace.models.agent_results import DiscoveryResult
from scitrace.services import ResourceService

DISCOVERY_SYSTEM_PROMPT = """You are the Discovery specialist in a scientific reproduction system.

Your responsibility is to find scientific resources, resolve their canonical identity when
necessary, and verify their truth, provenance, and resource-level usability when necessary.

Use the available resource discovery tools to find the resources needed for the request. Decide
which tools to use, what to search for, whether additional searches are necessary, and when enough
information has been collected.

Search results are candidates, not confirmed ResearchResources. The system automatically classifies
Search and Resolve observations as new_candidates, existing_resources, or ambiguous_candidates.
Use Resolve when identity evidence is insufficient and Verify when truth, provenance, or usability
needs confirmation. You decide which tools to call, in what order, and whether another query is
useful. Do not assume a fixed Search, Resolve, Verify sequence.

new_candidates and ambiguous_candidates are not eligible for DiscoveryResult. Before returning a
new resource, call verify_resource and use the verified_resource returned by that tool without
inventing or changing its ID. An existing_resources item is already globally confirmed and may be
reused without verification when it is not already in the parent-confirmed list. Account for each
resource category explicitly requested by the delegation; doing so is request fulfillment, not a
judgment that the overall resource set is sufficient for reproduction.

Do not submit the structured DiscoveryResult while an explicitly requested category that is absent
from the parent-confirmed list has neither a verified_resource nor an existing_resources match. If
verify_resource returns a matching verified_resource, include that exact resource in
discovered_resources; do not discard it or replace its ID.

Return only resources newly confirmed for this task during this invocation. They may be newly
verified resources or globally existing resources reused for this task, but must not include
resources already present in the parent-confirmed list. Keep ResourceSummary exactly consistent
with discovered_resources.

Do not analyze scientific methodology, design experiments, construct experiment specifications,
execute commands, or determine whether scientific reproduction succeeded.

Never invent resources or resource metadata that are not supported by tool results. If a search
returns no useful result, try a meaningfully different query when reasonable. Do not repeat
effectively identical searches. If reasonable alternatives are exhausted, return an empty
DiscoveryResult instead of continuing indefinitely.
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
        middleware=[ResourceDeduplicationMiddleware(resource_service)],
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


def build_discovery_agent_tool(
    discovery_agent: DiscoveryAgent,
    resource_service: ResourceService,
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
        resource_service.register_existing(parent["resources"])
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

        parent_ids = {resource.id for resource in parent["resources"]}
        raw_counts = {
            "paper_count": sum(
                resource.kind == "paper" for resource in result.discovered_resources
            ),
            "repository_count": sum(
                resource.kind == "repository" for resource in result.discovered_resources
            ),
            "dataset_count": sum(
                resource.kind == "dataset" for resource in result.discovered_resources
            ),
            "model_count": sum(
                resource.kind == "model" for resource in result.discovered_resources
            ),
        }
        if result.summary.model_dump(mode="json") != raw_counts:
            raise RuntimeError("DiscoveryResult.summary 与 discovered_resources 不一致")
        promoted = [resource_service.promote(resource) for resource in result.discovered_resources]
        discovered = [resource for resource in promoted if resource.id not in parent_ids]
        current_resources = _merge_resources(parent["resources"], discovered)
        counts = {
            "paper_count": sum(resource.kind == "paper" for resource in discovered),
            "repository_count": sum(resource.kind == "repository" for resource in discovered),
            "dataset_count": sum(resource.kind == "dataset" for resource in discovered),
            "model_count": sum(resource.kind == "model" for resource in discovered),
        }
        observation = {
            "action": "discovery_result",
            "summary": counts,
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
