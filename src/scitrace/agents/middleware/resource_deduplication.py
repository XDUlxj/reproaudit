"""Discovery Candidate 的确定性分类与 observation state 写入。"""

import json
from collections.abc import Callable, Collection
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain.messages import ToolMessage
from langgraph.types import Command
from pydantic import TypeAdapter, ValidationError

from scitrace.models.discovery import (
    ExistingResourceMatch,
    ResourceCandidate,
    SearchObservation,
)
from scitrace.services.errors import ResourceObservationError
from scitrace.services.resource import ResourceService

_CANDIDATE_LIST_ADAPTER = TypeAdapter(list[ResourceCandidate])


class ResourceDeduplicationMiddleware(AgentMiddleware):
    """把显式注册的 Candidate-producing Tool 输出转成双通道 observation。"""

    def __init__(
        self,
        resource_service: ResourceService,
        *,
        tool_names: Collection[str],
    ) -> None:
        self._resource_service = resource_service
        self._tool_names = frozenset(tool_names)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        result = handler(request)
        tool_name = request.tool_call["name"]
        if tool_name not in self._tool_names:
            return result
        if not isinstance(result, ToolMessage):
            raise ResourceObservationError(
                f"Candidate-producing Tool {tool_name} 未返回 ToolMessage"
            )

        candidates = self._parse_candidates(tool_name, result.content)
        observation = SearchObservation()
        for candidate in candidates:
            dedup = self._resource_service.deduplicate(candidate)
            if dedup.status == "new":
                observation.new_candidates.append(dedup.candidate)
            elif dedup.status == "ambiguous":
                observation.ambiguous_candidates.append(dedup.candidate)
            else:
                assert dedup.existing_resource is not None
                observation.existing_resources.append(
                    ExistingResourceMatch(
                        resource=dedup.existing_resource,
                        matched_by=dedup.matched_by or "strong_identity",
                        discovered_locations=candidate.locations,
                    )
                )

        message = result.model_copy(
            update={"content": observation.model_dump_json(), "name": tool_name}
        )
        return Command(
            update={
                "observed_new_candidates": observation.new_candidates,
                "observed_existing_resource_ids": [
                    match.resource.id for match in observation.existing_resources
                ],
                "messages": [message],
            }
        )

    @staticmethod
    def _parse_candidates(tool_name: str, content: Any) -> list[ResourceCandidate]:
        value = content
        if isinstance(content, str):
            try:
                value = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ResourceObservationError(
                    f"Candidate-producing Tool {tool_name} 返回了非法 JSON"
                ) from exc
        try:
            return _CANDIDATE_LIST_ADAPTER.validate_python(value)
        except ValidationError as exc:
            raise ResourceObservationError(
                f"Candidate-producing Tool {tool_name} 返回值不符合 list[ResourceCandidate]"
            ) from exc
