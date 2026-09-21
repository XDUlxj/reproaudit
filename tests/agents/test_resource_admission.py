"""Discovery 边界外 Resource Admission 的确定性测试。"""

import pytest

from scitrace.models import DatasetResource, PaperResource, ResearchResource, WebLocation
from scitrace.models.discovery import (
    DatasetCandidate,
    DiscoverySelection,
    PaperCandidate,
    ResourceCandidate,
    candidate_id,
)
from scitrace.services import (
    InvalidDiscoverySelectionError,
    ResourceAdmissionService,
    ResourceService,
)


class RecordingVerifier:
    def __init__(self, result: ResearchResource | None) -> None:
        self.result = result
        self.calls: list[ResourceCandidate] = []

    def verify(self, candidate: ResourceCandidate) -> ResearchResource | None:
        self.calls.append(candidate)
        return self.result


class RecordingRepository:
    def __init__(self, returned: ResearchResource) -> None:
        self.returned = returned
        self.calls: list[ResearchResource] = []
        self.canonical_keys: list[str] = []
        self.attachments: list[tuple[str, str]] = []

    def admit_verified(
        self, resource: ResearchResource, *, canonical_key: str
    ) -> ResearchResource:
        self.calls.append(resource)
        self.canonical_keys.append(canonical_key)
        return self.returned

    def attach_to_task(self, task_id: str, resource_id: str) -> None:
        self.attachments.append((task_id, resource_id))


def _candidate(doi: str | None = "10.1000/new") -> PaperCandidate:
    return PaperCandidate(
        name="New Paper",
        doi=doi,
        locations=[WebLocation(url="https://example.test/paper")],
    )


def _observed(candidate: ResourceCandidate) -> dict[str, ResourceCandidate]:
    return {candidate_id(candidate): candidate}


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
        observed_new_candidates={},
        observed_existing_resources={existing.id: existing},
        task_id="task-test",
    )

    assert [resource.id for resource in result.discovered_resources] == [existing.id]
    assert verifier.calls == []
    assert repository.calls == []


def test_new_resource_is_mandatorily_verified_and_persisted() -> None:
    candidate = _candidate()
    verified = PaperResource(id="paper-new", name="New Paper", doi=candidate.doi)
    verifier = RecordingVerifier(verified)
    repository = RecordingRepository(verified)
    admission = ResourceAdmissionService(
        resource_service=ResourceService(),
        verifier=verifier,
        repository=repository,
    )

    result = admission.admit(
        DiscoverySelection(selected_new_candidate_ids=[candidate_id(candidate)]),
        parent_resources=[],
        observed_new_candidates=_observed(candidate),
        observed_existing_resources={},
        task_id="task-test",
    )

    assert result.discovered_resources == [verified]
    assert verifier.calls == [candidate]
    assert repository.calls == [verified]
    assert repository.attachments == [("task-test", verified.id)]


def test_verify_failure_and_ambiguous_candidate_are_not_admitted() -> None:
    strong = _candidate()
    ambiguous = _candidate(None)
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
        DiscoverySelection(
            selected_new_candidate_ids=[candidate_id(strong), candidate_id(ambiguous)]
        ),
        parent_resources=[],
        observed_new_candidates={**_observed(strong), **_observed(ambiguous)},
        observed_existing_resources={},
        task_id="task-test",
    )

    assert result.discovered_resources == []
    assert verifier.calls == [strong]
    assert repository.calls == []


def test_unobserved_existing_id_is_rejected() -> None:
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

    with pytest.raises(InvalidDiscoverySelectionError):
        admission.admit(
            DiscoverySelection(
                selected_existing_resource_ids=[existing.id],
            ),
            parent_resources=[],
            observed_new_candidates={},
            observed_existing_resources={},
            task_id="task-test",
        )

    assert verifier.calls == []
    assert repository.calls == []


def test_unobserved_new_candidate_is_rejected() -> None:
    invented = _candidate("10.1000/invented")
    verified = PaperResource(name="Invented", doi=invented.doi)
    verifier = RecordingVerifier(verified)
    repository = RecordingRepository(verified)
    admission = ResourceAdmissionService(
        resource_service=ResourceService(), verifier=verifier, repository=repository
    )

    with pytest.raises(InvalidDiscoverySelectionError):
        admission.admit(
            DiscoverySelection(selected_new_candidate_ids=[candidate_id(invented)]),
            parent_resources=[],
            observed_new_candidates={},
            observed_existing_resources={},
            task_id="task-test",
        )

    assert verifier.calls == []
    assert repository.calls == []


def test_persistence_final_dedup_may_reuse_concurrently_created_resource() -> None:
    candidate = _candidate()
    verified = PaperResource(id="paper-new-at-verify", name="New", doi=candidate.doi)
    concurrently_created = PaperResource(
        id="paper-existing-at-persist",
        name="Existing",
        doi=candidate.doi,
    )
    verifier = RecordingVerifier(verified)
    repository = RecordingRepository(concurrently_created)
    admission = ResourceAdmissionService(
        resource_service=ResourceService(),
        verifier=verifier,
        repository=repository,
    )

    result = admission.admit(
        DiscoverySelection(selected_new_candidate_ids=[candidate_id(candidate)]),
        parent_resources=[],
        observed_new_candidates=_observed(candidate),
        observed_existing_resources={},
        task_id="task-test",
    )

    assert [resource.id for resource in result.discovered_resources] == [
        "paper-existing-at-persist"
    ]
    assert repository.calls == [verified]
    assert repository.attachments == [("task-test", concurrently_created.id)]


def test_verify_enriched_identity_is_used_for_final_admission() -> None:
    candidate = PaperCandidate(name="Paper", arxiv_id="2401.00001")
    verified = PaperResource(name="Paper", doi="10.1000/enriched", arxiv_id="2401.00001")
    verifier = RecordingVerifier(verified)
    repository = RecordingRepository(verified)
    admission = ResourceAdmissionService(
        resource_service=ResourceService(), verifier=verifier, repository=repository
    )

    admission.admit(
        DiscoverySelection(selected_new_candidate_ids=[candidate_id(candidate)]),
        parent_resources=[],
        observed_new_candidates=_observed(candidate),
        observed_existing_resources={},
        task_id="task-test",
    )

    assert repository.canonical_keys == ["paper:doi:10.1000/enriched"]


def test_candidate_id_selection_preserves_cifar10_location_for_verification() -> None:
    location = WebLocation(url="https://www.cs.toronto.edu/~kriz/cifar.html")
    candidate = DatasetCandidate(
        name="CIFAR-10",
        provider="torchvision",
        dataset_id="cifar10",
        version="1",
        locations=[location],
    )
    verified = DatasetResource(
        name="CIFAR-10",
        version="1",
        locations=[location],
        metadata={"provider": "torchvision", "dataset_id": "cifar10"},
    )
    verifier = RecordingVerifier(verified)
    repository = RecordingRepository(verified)
    admission = ResourceAdmissionService(
        resource_service=ResourceService(), verifier=verifier, repository=repository
    )

    result = admission.admit(
        DiscoverySelection(selected_new_candidate_ids=[candidate_id(candidate)]),
        parent_resources=[],
        observed_new_candidates=_observed(candidate),
        observed_existing_resources={},
        task_id="task-test",
    )

    assert verifier.calls[0].locations == [location]
    assert result.discovered_resources == [verified]


def test_distinct_observations_of_same_resource_admit_only_once() -> None:
    first = PaperCandidate(
        name="Paper via arXiv", doi="10.1000/same", locations=[WebLocation(url="https://a")]
    )
    second = PaperCandidate(
        name="Paper via publisher",
        doi="10.1000/same",
        locations=[WebLocation(url="https://b")],
    )
    verified = PaperResource(id="paper-same", name="Paper", doi="10.1000/same")
    verifier = RecordingVerifier(verified)
    repository = RecordingRepository(verified)
    admission = ResourceAdmissionService(
        resource_service=ResourceService(), verifier=verifier, repository=repository
    )

    result = admission.admit(
        DiscoverySelection(
            selected_new_candidate_ids=[candidate_id(first), candidate_id(second)]
        ),
        parent_resources=[],
        observed_new_candidates={**_observed(first), **_observed(second)},
        observed_existing_resources={},
        task_id="task-test",
    )

    assert result.discovered_resources == [verified]
    assert verifier.calls == [first]
    assert repository.calls == [verified]


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
        observed_new_candidates={},
        observed_existing_resources={parent.id: parent},
        task_id="task-test",
    )

    assert result.discovered_resources == []
    assert result.summary.model_dump() == {
        "paper_count": 0,
        "repository_count": 0,
        "dataset_count": 0,
        "model_count": 0,
    }
