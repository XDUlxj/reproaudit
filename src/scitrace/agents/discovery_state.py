"""Discovery compiled graph 的 authoritative observation state。"""

from typing import Annotated

from langchain.agents.middleware import AgentState

from scitrace.models.discovery import (
    DiscoverySelection,
    ResourceCandidate,
)
from scitrace.models.resource import ResearchResource
from scitrace.services.errors import CandidateIdentityCollisionError


def merge_observed_candidate_maps(
    left: dict[str, ResourceCandidate],
    right: dict[str, ResourceCandidate],
) -> dict[str, ResourceCandidate]:
    """合并 Candidate delta；发现同 ID 异 payload 时立即失败。"""
    merged = dict(left)
    for candidate_id, candidate in right.items():
        existing = merged.get(candidate_id)
        if existing is not None and existing != candidate:
            raise CandidateIdentityCollisionError(
                f"Candidate ID {candidate_id} 对应了不同 payload"
            )
        merged[candidate_id] = candidate
    return merged


def merge_observed_resource_maps(
    left: dict[str, ResearchResource],
    right: dict[str, ResearchResource],
) -> dict[str, ResearchResource]:
    """合并 EXISTING Resource delta；禁止同稳定 ID 静默覆盖。"""
    merged = dict(left)
    for resource_id, resource in right.items():
        existing = merged.get(resource_id)
        if existing is not None and existing != resource:
            raise CandidateIdentityCollisionError(
                f"Resource ID {resource_id} 对应了不同 payload"
            )
        merged[resource_id] = resource
    return merged


class DiscoveryState(AgentState[DiscoverySelection]):
    """Discovery invocation 的消息状态与可验证 observation provenance。"""

    observed_new_candidates: Annotated[
        dict[str, ResourceCandidate], merge_observed_candidate_maps
    ]
    observed_existing_resources: Annotated[
        dict[str, ResearchResource], merge_observed_resource_maps
    ]
