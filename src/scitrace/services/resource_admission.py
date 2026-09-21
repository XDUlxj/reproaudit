"""Discovery Agent 边界外的确定性资源准入流程。"""

import json
from typing import Any, Protocol

from scitrace.models import ResearchResource
from scitrace.models.agent_results import DiscoveryResult, ResourceSummary
from scitrace.models.discovery import DiscoverySelection
from scitrace.persistence import ResourceRepository
from scitrace.services.resource import ResourceService


class ResourceVerifier(Protocol):
    """验证 NEW Candidate；失败时返回 None。"""

    def verify(self, candidate: dict[str, Any]) -> ResearchResource | None: ...


class ResourceAdmissionService:
    """把 Agent 选择转换为当前 invocation 新确认的正式资源。"""

    def __init__(
        self,
        *,
        resource_service: ResourceService,
        verifier: ResourceVerifier,
        repository: ResourceRepository,
    ) -> None:
        self._resource_service = resource_service
        self._verifier = verifier
        self._repository = repository

    def admit(
        self,
        selection: DiscoverySelection,
        *,
        parent_resources: list[ResearchResource],
        observed_new_candidates: list[dict[str, Any]],
        observed_existing_resource_ids: set[str],
        task_id: str,
    ) -> DiscoveryResult:
        """EXISTING 直接复用；NEW 强制 Verify 后交给 Persistence 原子准入。"""
        self._resource_service.register_existing(parent_resources)
        parent_resource_ids = {resource.id for resource in parent_resources}
        admitted: dict[str, ResearchResource] = {}
        observed_fingerprints = {
            json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str)
            for candidate in observed_new_candidates
        }

        for resource_id in selection.selected_existing_resource_ids:
            if resource_id not in observed_existing_resource_ids:
                continue
            resource = self._resource_service.get(resource_id)
            if resource is not None and resource.id not in parent_resource_ids:
                admitted[resource.id] = resource

        for candidate in selection.selected_new_candidates:
            fingerprint = json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str)
            if fingerprint not in observed_fingerprints:
                continue
            dedup = self._resource_service.deduplicate(candidate)
            if dedup.status == "ambiguous":
                continue
            if dedup.status == "existing":
                assert dedup.existing_resource is not None
                resource = dedup.existing_resource
            else:
                verified = self._verifier.verify(candidate)
                if verified is None:
                    continue
                # Verify 可能补全 DOI 等权威身份，最终 key 必须基于验证结果重算。
                canonical_key = self._resource_service.canonical_key(verified)
                if canonical_key is None:
                    continue
                resource = self._repository.admit_verified(
                    verified,
                    canonical_key=canonical_key,
                )
                self._resource_service.register_existing([resource])
            if resource.id not in parent_resource_ids:
                admitted[resource.id] = resource

        resources = list(admitted.values())
        for resource in resources:
            self._repository.attach_to_task(task_id, resource.id)
        return DiscoveryResult(
            discovered_resources=resources,
            summary=ResourceSummary(
                paper_count=sum(resource.kind == "paper" for resource in resources),
                repository_count=sum(resource.kind == "repository" for resource in resources),
                dataset_count=sum(resource.kind == "dataset" for resource in resources),
                model_count=sum(resource.kind == "model" for resource in resources),
            ),
        )
