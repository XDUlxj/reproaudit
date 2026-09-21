"""Discovery 边界外 Resource Admission 的确定性测试。"""

from typing import Any

from scitrace.models import PaperResource, ResearchResource
from scitrace.models.discovery import DiscoverySelection
from scitrace.services import ResourceAdmissionService, ResourceService


class RecordingVerifier:
    def __init__(self, result: ResearchResource | None) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def verify(self, candidate: dict[str, Any]) -> ResearchResource | None:
        self.calls.append(candidate)
        return self.result


class RecordingRepository:
    def __init__(self, returned: ResearchResource) -> None:
        self.returned = returned
        self.calls: list[ResearchResource] = []
        self.attachments: list[tuple[str, str]] = []

    def admit_verified(
        self, resource: ResearchResource, *, canonical_key: str
    ) -> ResearchResource:
        self.calls.append(resource)
        return self.returned

    def attach_to_task(self, task_id: str, resource_id: str) -> None:
        self.attachments.append((task_id, resource_id))


def _candidate(doi: str = "10.1000/new") -> dict[str, Any]:
    return {
        "kind": "paper",
        "title": "New Paper",
        "doi": doi,
        "url": "https://example.test/paper",
    }


def test_existing_resource_is_reused_without_verify_or_persist() -> None:
    existing = PaperResource(id="paper-existing", name="Existing", doi="10.1000/existing")
    verifier = RecordingVerifier(None)
    repository = RecordingRepository(existing)
    admission = ResourceAdmissionService(
        resource_service=ResourceService([existing]),
        verifier=verifier,
        repository=repository,
    )

    result = admission.admit(
        DiscoverySelection(selected_existing_resource_ids=[existing.id]),
        parent_resources=[],
        observed_new_candidates=[],
        observed_existing_resource_ids={existing.id},
        task_id="task-test",
    )

    assert [resource.id for resource in result.discovered_resources] == [existing.id]
    assert verifier.calls == []
    assert repository.calls == []


def test_new_resource_is_mandatorily_verified_and_persisted() -> None:
    candidate = _candidate()
    verified = PaperResource(id="paper-new", name="New Paper", doi=candidate["doi"])
    verifier = RecordingVerifier(verified)
    repository = RecordingRepository(verified)
    admission = ResourceAdmissionService(
        resource_service=ResourceService(),
        verifier=verifier,
        repository=repository,
    )

    result = admission.admit(
        DiscoverySelection(selected_new_candidates=[candidate]),
        parent_resources=[],
        observed_new_candidates=[candidate],
        observed_existing_resource_ids=set(),
        task_id="task-test",
    )

    assert result.discovered_resources == [verified]
    assert verifier.calls == [candidate]
    assert repository.calls == [verified]
    assert repository.attachments == [("task-test", verified.id)]


def test_verify_failure_and_ambiguous_candidate_are_not_admitted() -> None:
    strong = _candidate()
    ambiguous = {"kind": "paper", "title": "Weak Paper"}
    verifier = RecordingVerifier(None)
    repository = RecordingRepository(
        PaperResource(id="unused", name="Unused", doi="10.1000/unused")
    )
    admission = ResourceAdmissionService(
        resource_service=ResourceService(),
        verifier=verifier,
        repository=repository,
    )

    result = admission.admit(
        DiscoverySelection(selected_new_candidates=[strong, ambiguous]),
        parent_resources=[],
        observed_new_candidates=[strong, ambiguous],
        observed_existing_resource_ids=set(),
        task_id="task-test",
    )

    assert result.discovered_resources == []
    assert verifier.calls == [strong]
    assert repository.calls == []


def test_unobserved_candidate_or_existing_id_is_rejected() -> None:
    invented = _candidate("10.1000/invented")
    existing = PaperResource(id="paper-existing", name="Existing", doi="10.1000/existing")
    verifier = RecordingVerifier(
        PaperResource(id="paper-invented", name="Invented", doi="10.1000/invented")
    )
    repository = RecordingRepository(verifier.result)  # type: ignore[arg-type]
    admission = ResourceAdmissionService(
        resource_service=ResourceService([existing]),
        verifier=verifier,
        repository=repository,
    )

    result = admission.admit(
        DiscoverySelection(
            selected_new_candidates=[invented],
            selected_existing_resource_ids=[existing.id],
        ),
        parent_resources=[],
        observed_new_candidates=[],
        observed_existing_resource_ids=set(),
        task_id="task-test",
    )

    assert result.discovered_resources == []
    assert verifier.calls == []
    assert repository.calls == []


def test_persistence_final_dedup_may_reuse_concurrently_created_resource() -> None:
    candidate = _candidate()
    verified = PaperResource(id="paper-new-at-verify", name="New", doi=candidate["doi"])
    concurrently_created = PaperResource(
        id="paper-existing-at-persist",
        name="Existing",
        doi=candidate["doi"],
    )
    verifier = RecordingVerifier(verified)
    repository = RecordingRepository(concurrently_created)
    admission = ResourceAdmissionService(
        resource_service=ResourceService(),
        verifier=verifier,
        repository=repository,
    )

    result = admission.admit(
        DiscoverySelection(selected_new_candidates=[candidate]),
        parent_resources=[],
        observed_new_candidates=[candidate],
        observed_existing_resource_ids=set(),
        task_id="task-test",
    )

    assert [resource.id for resource in result.discovered_resources] == [
        "paper-existing-at-persist"
    ]
    assert repository.calls == [verified]
    assert repository.attachments == [("task-test", concurrently_created.id)]


def test_parent_resource_is_removed_from_delta_and_summary_is_recomputed() -> None:
    parent = PaperResource(id="paper-parent", name="Parent", doi="10.1000/parent")
    verifier = RecordingVerifier(None)
    repository = RecordingRepository(parent)
    admission = ResourceAdmissionService(
        resource_service=ResourceService([parent]),
        verifier=verifier,
        repository=repository,
    )

    result = admission.admit(
        DiscoverySelection(selected_existing_resource_ids=[parent.id]),
        parent_resources=[parent],
        observed_new_candidates=[],
        observed_existing_resource_ids={parent.id},
        task_id="task-test",
    )

    assert result.discovered_resources == []
    assert result.summary.model_dump() == {
        "paper_count": 0,
        "repository_count": 0,
        "dataset_count": 0,
        "model_count": 0,
    }
