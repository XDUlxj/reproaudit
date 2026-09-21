"""Typed Candidate、ResourceService 与 observation middleware 契约测试。"""

import json
from typing import Any, cast

import pytest
from langchain.agents.middleware import ToolCallRequest
from langchain.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import TypeAdapter, ValidationError

from scitrace.agents.discovery_state import (
    merge_observed_candidate_maps,
    merge_observed_resource_maps,
)
from scitrace.agents.middleware import ResourceDeduplicationMiddleware
from scitrace.models import DatasetResource, ModelResource, PaperResource, WebLocation
from scitrace.models.discovery import (
    DatasetCandidate,
    DeduplicationResult,
    ModelCandidate,
    ObservedCandidate,
    PaperCandidate,
    RepositoryCandidate,
    ResourceCandidate,
    SearchObservation,
    candidate_id,
)
from scitrace.services import (
    CandidateIdentityCollisionError,
    ResourceObservationError,
    ResourceService,
)


def _request(tool_name: str = "paper_lookup") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": tool_name, "args": {}, "id": "call-1", "type": "tool_call"},
        tool=None,
        state={},
        runtime=cast(Any, None),
    )


def _tool_message(candidates: list[object]) -> ToolMessage:
    content = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in candidates
    ]
    return ToolMessage(name="paper_lookup", tool_call_id="call-1", content=json.dumps(content))


def _middleware(*resources: PaperResource) -> ResourceDeduplicationMiddleware:
    return ResourceDeduplicationMiddleware(
        ResourceService(resources), tool_names={"paper_lookup"}
    )


def _observation(command: Command[Any]) -> SearchObservation:
    message = command.update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call-1"
    return SearchObservation.model_validate_json(str(message.content))


def test_candidate_models_are_discriminated_runtime_dtos() -> None:
    adapter = TypeAdapter(ResourceCandidate)
    candidates = [
        PaperCandidate(name="Paper", doi="10.1/a"),
        RepositoryCandidate(name="Repo", provider="github.com", owner="o", repository="r"),
        DatasetCandidate(name="Data", provider="hf", dataset_id="d", version="1"),
        ModelCandidate(name="Model", provider="hf", model_id="m", revision="main"),
    ]
    assert [adapter.validate_python(item.model_dump()).kind for item in candidates] == [
        "paper", "repository", "dataset", "model"
    ]
    for candidate in candidates:
        assert {"id", "created_at", "schema_version"}.isdisjoint(candidate.model_fields_set)
    with pytest.raises(ValidationError):
        PaperCandidate(name="Paper", doi="10.1/a", unexpected=True)  # type: ignore[call-arg]


def test_candidate_id_is_stable_and_tracks_full_observation() -> None:
    first = PaperCandidate(name="ZipIt!", doi="10.1/same")
    second = PaperCandidate(name="ZIPIT! Merging Models", doi="10.1/same")

    assert candidate_id(first) == candidate_id(first.model_copy())
    assert candidate_id(first) != candidate_id(second)
    assert ResourceService().canonical_key(first) == ResourceService().canonical_key(second)
    assert candidate_id(first).startswith("cand_")


def test_observed_candidate_and_id_only_selection_contract() -> None:
    candidate = PaperCandidate(name="Paper", doi="10.1/a")
    observed = ObservedCandidate(candidate_id=candidate_id(candidate), candidate=candidate)

    assert observed.candidate == candidate
    from scitrace.models.discovery import DiscoverySelection

    selection = DiscoverySelection(selected_new_candidate_ids=[observed.candidate_id])
    assert selection.selected_new_candidate_ids == [observed.candidate_id]
    with pytest.raises(ValidationError):
        DiscoverySelection(selected_new_candidates=[candidate])  # type: ignore[call-arg]


def test_map_reducers_are_idempotent_and_detect_collisions() -> None:
    first = PaperCandidate(name="A", doi="10.1/a")
    changed = PaperCandidate(name="Changed", doi="10.1/a")
    key = candidate_id(first)
    assert merge_observed_candidate_maps({key: first}, {key: first}) == {key: first}
    with pytest.raises(CandidateIdentityCollisionError):
        merge_observed_candidate_maps({key: first}, {key: changed})

    resource = PaperResource(id="R1", name="Paper", doi="10.1/a")
    assert merge_observed_resource_maps({resource.id: resource}, {resource.id: resource}) == {
        resource.id: resource
    }
    with pytest.raises(CandidateIdentityCollisionError):
        merge_observed_resource_maps(
            {resource.id: resource},
            {resource.id: resource.model_copy(update={"name": "Changed"})},
        )


def test_parallel_observation_updates_are_merged_by_discovery_state() -> None:
    """模拟并行 Tool Call 的多个 Command delta，证明不会 last-write-wins。"""
    from scitrace.agents.discovery_state import DiscoveryState

    first = PaperCandidate(name="A", doi="10.1/a")
    shared = PaperCandidate(name="B", doi="10.1/b")
    third = PaperCandidate(name="C", doi="10.1/c")
    first_id, shared_id, third_id = map(candidate_id, (first, shared, third))
    resource_1 = PaperResource(id="R1", name="R1", doi="10.1/r1")
    resource_2 = PaperResource(id="R2", name="R2", doi="10.1/r2")
    graph = StateGraph(DiscoveryState)
    graph.add_node(
        "tool_a",
        lambda _: {
            "observed_new_candidates": {first_id: first, shared_id: shared},
            "observed_existing_resources": {resource_1.id: resource_1},
        },
    )
    graph.add_node(
        "tool_b",
        lambda _: {
            "observed_new_candidates": {shared_id: shared, third_id: third},
            "observed_existing_resources": {
                resource_1.id: resource_1,
                resource_2.id: resource_2,
            },
        },
    )
    graph.add_edge(START, "tool_a")
    graph.add_edge(START, "tool_b")
    graph.add_edge("tool_a", END)
    graph.add_edge("tool_b", END)

    result = graph.compile().invoke({"messages": []})

    assert result["observed_new_candidates"] == {
        first_id: first, shared_id: shared, third_id: third
    }
    assert result["observed_existing_resources"] == {
        resource_1.id: resource_1, resource_2.id: resource_2
    }


def test_middleware_returns_observation_and_records_only_selectable_delta() -> None:
    existing = PaperResource(id="paper-existing", name="Existing", doi="10.1/existing")
    candidates = [
        PaperCandidate(name="New", doi="10.1/new"),
        PaperCandidate(
            name="Existing representation",
            doi="https://doi.org/10.1/EXISTING",
            locations=[WebLocation(url="https://publisher.test/paper")],
        ),
        PaperCandidate(name="Ambiguous"),
    ]

    result = _middleware(existing).wrap_tool_call(
        _request(), lambda _: _tool_message(candidates)
    )

    assert isinstance(result, Command)
    observation = _observation(result)
    observed = observation.new_candidates[0]
    assert observed.candidate_id == candidate_id(candidates[0])
    assert observed.candidate == candidates[0]
    assert observation.ambiguous_candidates == [candidates[2]]
    assert observation.existing_resources[0].resource.id == existing.id
    assert observation.existing_resources[0].discovered_locations == candidates[1].locations
    assert result.update["observed_new_candidates"] == {
        observed.candidate_id: candidates[0]
    }
    assert result.update["observed_existing_resources"] == {existing.id: existing}


def test_empty_candidate_result_is_valid_empty_observation() -> None:
    result = _middleware().wrap_tool_call(_request(), lambda _: _tool_message([]))
    assert isinstance(result, Command)
    assert _observation(result) == SearchObservation()


def test_unregistered_tool_is_not_intercepted() -> None:
    original = _tool_message([])
    result = _middleware().wrap_tool_call(_request("inspect_paper"), lambda _: original)
    assert result is original


def test_registered_tool_with_invalid_output_fails_fast() -> None:
    with pytest.raises(ResourceObservationError):
        _middleware().wrap_tool_call(
            _request(),
            lambda _: ToolMessage(tool_call_id="call-1", content="not-json"),
        )


def test_resource_service_supports_all_canonical_identity_types() -> None:
    dataset = DatasetResource(
        id="dataset-existing", name="Dataset", version="1",
        metadata={"provider": "provider", "dataset_id": "dataset"},
    )
    model = ModelResource(
        id="model-existing", name="Model", revision="main",
        metadata={"provider": "provider", "model_id": "model"},
    )
    service = ResourceService([dataset, model])

    assert service.deduplicate(
        DatasetCandidate(name="Dataset", provider="PROVIDER", dataset_id="dataset", version="1")
    ).status == "existing"
    assert service.deduplicate(
        DatasetCandidate(name="Weak", provider="provider", dataset_id="weak")
    ).status == "ambiguous"
    assert service.deduplicate(
        ModelCandidate(name="Model", provider="provider", model_id="model", revision="MAIN")
    ).status == "existing"


def test_deduplication_result_rejects_inconsistent_status_payload() -> None:
    candidate = PaperCandidate(name="Paper", doi="10.1/new")
    with pytest.raises(ValidationError):
        DeduplicationResult(status="existing", candidate=candidate)
    with pytest.raises(ValidationError):
        DeduplicationResult(
            status="new",
            candidate=candidate,
            existing_resource=PaperResource(name="Existing", doi="10.1/existing"),
            matched_by="doi",
        )
