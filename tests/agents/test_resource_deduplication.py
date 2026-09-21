"""ResourceDeduplicationMiddleware 与 ResourceService 的数据完整性测试。"""

import json
from typing import Any, cast

import pytest
from langchain.agents.middleware import ToolCallRequest
from langchain.messages import ToolMessage
from pydantic import ValidationError

from scitrace.agents.middleware import ResourceDeduplicationMiddleware
from scitrace.models import (
    DatasetResource,
    ModelResource,
    PaperResource,
    RepositoryResource,
    WebLocation,
)
from scitrace.models.discovery import DeduplicationResult
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


def test_repository_search_result_is_deduplicated() -> None:
    existing = RepositoryResource(
        id="repository-existing",
        name="foo/bar",
        locations=[WebLocation(url="https://github.com/foo/bar")],
    )
    middleware = ResourceDeduplicationMiddleware(ResourceService([existing]))
    candidate = {
        "kind": "repository",
        "provider": "github.com",
        "owner": "foo",
        "name": "bar",
        "canonical_url": "https://github.com/foo/bar.git",
    }

    result = middleware.wrap_tool_call(
        _request("search_repositories"),
        lambda _: _tool_message([candidate]),
    )

    assert isinstance(result, ToolMessage)
    observation = json.loads(str(result.content))
    assert observation["new_candidates"] == []
    assert observation["ambiguous_candidates"] == []
    assert observation["existing_resources"][0]["resource"]["id"] == "repository-existing"


def test_dataset_and_model_strong_identity_support_new_existing_and_ambiguous() -> None:
    dataset = DatasetResource(
        id="dataset-existing",
        name="Dataset",
        version="1",
        metadata={"provider": "provider", "dataset_id": "dataset"},
    )
    model = ModelResource(
        id="model-existing",
        name="Model",
        revision="main",
        metadata={"provider": "provider", "model_id": "model"},
    )
    service = ResourceService([dataset, model])

    assert service.deduplicate(
        {
            "kind": "dataset",
            "provider": "PROVIDER",
            "dataset_id": "dataset",
            "version": "1",
        }
    ).status == "existing"
    assert service.deduplicate(
        {
            "kind": "dataset",
            "provider": "provider",
            "dataset_id": "new",
            "version": "1",
        }
    ).status == "new"
    assert service.deduplicate(
        {"kind": "dataset", "provider": "provider", "name": "weak"}
    ).status == "ambiguous"
    assert service.deduplicate(
        {
            "kind": "model",
            "provider": "provider",
            "model_id": "model",
            "revision": "MAIN",
        }
    ).status == "existing"
    assert service.deduplicate(
        {"kind": "model", "provider": "provider", "model_id": "weak"}
    ).status == "ambiguous"


@pytest.mark.parametrize(
    ("tool_name", "candidate"),
    [
        ("search_papers", {"kind": "paper", "doi": "10.1000/paper"}),
        (
            "search_repositories",
            {
                "kind": "repository",
                "provider": "github.com",
                "owner": "owner",
                "name": "repo",
            },
        ),
        (
            "search_datasets",
            {
                "kind": "dataset",
                "provider": "provider",
                "dataset_id": "dataset",
                "version": "1",
            },
        ),
        (
            "search_models",
            {
                "kind": "model",
                "provider": "provider",
                "model_id": "model",
                "revision": "main",
            },
        ),
    ],
)
def test_middleware_intercepts_all_four_search_tools(
    tool_name: str,
    candidate: dict[str, Any],
) -> None:
    middleware = ResourceDeduplicationMiddleware(ResourceService())

    result = middleware.wrap_tool_call(
        _request(tool_name),
        lambda _: _tool_message([candidate]),
    )

    assert isinstance(result, ToolMessage)
    observation = json.loads(str(result.content))
    assert observation["new_candidates"] == [candidate]
    assert observation["existing_resources"] == []
    assert observation["ambiguous_candidates"] == []


def test_empty_search_becomes_empty_observation_instead_of_error() -> None:
    middleware = ResourceDeduplicationMiddleware(ResourceService())

    result = middleware.wrap_tool_call(
        _request("search_papers"),
        lambda _: _tool_message([]),
    )

    assert isinstance(result, ToolMessage)
    assert json.loads(str(result.content)) == {
        "new_candidates": [],
        "existing_resources": [],
        "ambiguous_candidates": [],
    }


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


def test_deduplication_result_rejects_inconsistent_status_payload() -> None:
    with pytest.raises(ValidationError):
        DeduplicationResult(status="existing", candidate={"kind": "paper"})
    with pytest.raises(ValidationError):
        DeduplicationResult(
            status="new",
            candidate={"kind": "paper", "doi": "10.1000/new"},
            existing_resource=PaperResource(
                id="paper-existing",
                name="Existing",
                doi="10.1000/existing",
            ),
            matched_by="doi",
        )
