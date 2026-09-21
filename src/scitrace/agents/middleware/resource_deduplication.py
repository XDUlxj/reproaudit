"""Discovery Search/Resolve 结果的自动资源去重中间件。"""

import json
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain.messages import ToolMessage
from langgraph.types import Command

from scitrace.models.discovery import ExistingResourceMatch, SearchObservation
from scitrace.services.resource import ResourceService

_DEDUPLICATED_TOOLS = {
    "search_papers",
    "search_repositories",
    "search_datasets",
    "search_models",
}


class ResourceDeduplicationMiddleware(AgentMiddleware):
    """自动执行强身份去重，但不替 DiscoveryAgent 决定后续工具。"""

    def __init__(self, resource_service: ResourceService) -> None:
        self._resource_service = resource_service

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        result = handler(request)
        tool_name = request.tool_call["name"]
        if tool_name not in _DEDUPLICATED_TOOLS or not isinstance(result, ToolMessage):
            return result

        candidates = self._parse_candidates(result.content)
        if candidates is None:
            return result
        observation = SearchObservation()
        for candidate in candidates:
            dedup = self._resource_service.deduplicate(candidate)
            if dedup.status == "new":
                observation.new_candidates.append(dedup.candidate)
            elif dedup.status == "ambiguous":
                observation.ambiguous_candidates.append(dedup.candidate)
            else:
                assert dedup.existing_resource is not None
                locations = dedup.candidate.get("locations", [])
                if not locations and dedup.candidate.get("url"):
                    locations = [{"kind": "web", "url": dedup.candidate["url"]}]
                observation.existing_resources.append(
                    ExistingResourceMatch(
                        resource=dedup.existing_resource,
                        matched_by=dedup.matched_by or "strong_identity",
                        discovered_locations=locations,
                    )
                )
        return result.model_copy(
            update={
                "content": json.dumps(observation.model_dump(mode="json"), ensure_ascii=False)
            }
        )

    @staticmethod
    def _parse_candidates(content: Any) -> list[dict[str, Any]] | None:
        if isinstance(content, str):
            try:
                value = json.loads(content)
            except json.JSONDecodeError:
                return None
        else:
            value = content
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
        return None
