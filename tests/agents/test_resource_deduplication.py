"""ResourceDeduplicationMiddleware 与 ResourceService 的数据完整性测试。"""

import json
from typing import Any, cast

from langchain.agents.middleware import ToolCallRequest
from langchain.messages import ToolMessage

from scitrace.agents.middleware import ResourceDeduplicationMiddleware
from scitrace.models import PaperResource, RepositoryResource, WebLocation
from scitrace.services import ResourceService


def _request(tool_name: str) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": tool_name, "args": {}, "id": "call-1", "type": "tool_call"},
        tool=None,
        state={},
        runtime=cast(Any, None),
    )


def _tool_message(content: object) -> ToolMessage:
    return ToolMessage(
        name="search_papers",
        tool_call_id="call-1",
        content=json.dumps(content),
    )


def test_middleware_classifies_new_existing_and_ambiguous_without_dropping_results() -> None:
    existing = PaperResource(
        id="paper-existing",
        name="Existing Paper",
        doi="10.1000/existing",
        locations=[WebLocation(url="https://arxiv.org/abs/existing")],
    )
    middleware = ResourceDeduplicationMiddleware(ResourceService([existing]))
    candidates = [
        {
            "kind": "paper",
            "title": "New Paper",
            "doi": "10.1000/new",
            "url": "https://example.test/new",
        },
        {
            "kind": "paper",
            "title": "Existing Paper",
            "doi": "https://doi.org/10.1000/EXISTING",
            "url": "https://publisher.test/existing",
        },
        {"kind": "paper", "title": "Weak Identity", "url": "https://example.test/weak"},
    ]

    result = middleware.wrap_tool_call(
        _request("search_papers"),
        lambda _: _tool_message(candidates),
    )

    assert isinstance(result, ToolMessage)
    observation = json.loads(str(result.content))
    assert len(observation["new_candidates"]) == 1
    assert len(observation["existing_resources"]) == 1
    assert len(observation["ambiguous_candidates"]) == 1
    match = observation["existing_resources"][0]
    assert match["resource"]["id"] == "paper-existing"
    assert match["matched_by"] == "doi"
    assert match["discovered_locations"] == [
        {"kind": "web", "url": "https://publisher.test/existing"}
    ]


def test_resolve_result_is_deduplicated_again() -> None:
    existing = RepositoryResource(
        id="repository-existing",
        name="foo/bar",
        locations=[WebLocation(url="https://github.com/foo/bar")],
    )
    middleware = ResourceDeduplicationMiddleware(ResourceService([existing]))
    resolved = {
        "kind": "repository",
        "provider": "github.com",
        "owner": "foo",
        "name": "bar",
        "canonical_url": "https://github.com/foo/bar.git",
    }

    result = middleware.wrap_tool_call(
        _request("resolve_resource_identity"),
        lambda _: _tool_message(resolved),
    )

    assert isinstance(result, ToolMessage)
    observation = json.loads(str(result.content))
    assert observation["new_candidates"] == []
    assert observation["ambiguous_candidates"] == []
    assert observation["existing_resources"][0]["resource"]["id"] == "repository-existing"


def test_parent_resources_can_be_registered_for_automatic_deduplication() -> None:
    service = ResourceService()
    parent_resource = PaperResource(
        id="paper-parent",
        name="Parent Paper",
        doi="10.1000/parent",
    )
    service.register_existing([parent_resource])

    result = service.deduplicate(
        {
            "kind": "paper",
            "title": "Same Paper From Search",
            "doi": "https://doi.org/10.1000/PARENT",
        }
    )

    assert result.status == "existing"
    assert result.existing_resource is not None
    assert result.existing_resource.id == "paper-parent"
