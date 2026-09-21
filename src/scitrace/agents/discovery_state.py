"""Discovery compiled graph 的 authoritative observation state。"""

from typing import Annotated

from langchain.agents.middleware import AgentState

from scitrace.models.discovery import (
    DiscoverySelection,
    ResourceCandidate,
    candidate_fingerprint,
)


def merge_observed_candidates(
    left: list[ResourceCandidate],
    right: list[ResourceCandidate],
) -> list[ResourceCandidate]:
    """按完整 observation 指纹稳定合并，不执行 Resource identity 去重。"""
    merged: dict[str, ResourceCandidate] = {}
    for candidate in [*left, *right]:
        merged.setdefault(candidate_fingerprint(candidate), candidate)
    return list(merged.values())


def merge_resource_ids(left: list[str], right: list[str]) -> list[str]:
    """稳定集合并集，支持并行 Tool Call 的 state delta。"""
    return list(dict.fromkeys([*left, *right]))


class DiscoveryState(AgentState[DiscoverySelection]):
    """Discovery invocation 的消息状态与可验证 observation provenance。"""

    observed_new_candidates: Annotated[
        list[ResourceCandidate], merge_observed_candidates
    ]
    observed_existing_resource_ids: Annotated[list[str], merge_resource_ids]
