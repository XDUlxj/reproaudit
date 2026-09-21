"""Discovery tools 与去重层之间的运行时数据契约，不属于持久化 Entity。"""

import json
from hashlib import sha256
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitrace.models.resource import ResearchResource, ResourceLocation


class CandidateBase(BaseModel):
    """外部搜索结果规范化后的运行时 DTO，不是持久化 Entity。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["paper", "repository", "dataset", "model"]
    name: str = Field(min_length=1)
    locations: list[ResourceLocation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaperCandidate(CandidateBase):
    kind: Literal["paper"] = "paper"
    doi: str | None = None
    arxiv_id: str | None = None


class RepositoryCandidate(CandidateBase):
    kind: Literal["repository"] = "repository"
    provider: str
    owner: str
    repository: str


class DatasetCandidate(CandidateBase):
    kind: Literal["dataset"] = "dataset"
    provider: str
    dataset_id: str
    version: str | None = None


class ModelCandidate(CandidateBase):
    kind: Literal["model"] = "model"
    provider: str
    model_id: str
    revision: str | None = None


ResourceCandidate = Annotated[
    PaperCandidate | RepositoryCandidate | DatasetCandidate | ModelCandidate,
    Field(discriminator="kind"),
]


def candidate_fingerprint(candidate: ResourceCandidate) -> str:
    """计算完整 Candidate observation 的稳定 SHA-256 指纹。"""
    payload = json.dumps(
        candidate.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def candidate_id(candidate: ResourceCandidate) -> str:
    """生成仅在当前 Discovery invocation 内使用的 opaque observation handle。"""
    return f"cand_{candidate_fingerprint(candidate)}"


class ObservedCandidate(BaseModel):
    """NEW Candidate 的引用 ID 与 authoritative 原始 payload。"""

    candidate_id: str
    candidate: ResourceCandidate


class ExistingResourceMatch(BaseModel):
    """Candidate 通过强身份标识匹配到的已存在资源。"""

    resource: ResearchResource
    matched_by: str
    discovered_locations: list[ResourceLocation] = Field(default_factory=list)


class SearchObservation(BaseModel):
    """Search Candidate 经确定性身份去重后的标准化三态观察。

    NEW、EXISTING、AMBIGUOUS Candidate 均显式返回给 DiscoveryAgent，
    任何 Candidate 都不会在去重过程中静默消失。
    """

    new_candidates: list[ObservedCandidate] = Field(default_factory=list)
    existing_resources: list[ExistingResourceMatch] = Field(default_factory=list)
    ambiguous_candidates: list[ResourceCandidate] = Field(default_factory=list)


class DeduplicationResult(BaseModel):
    """ResourceService 对单个 Candidate 的确定性身份判断。"""

    status: Literal["new", "existing", "ambiguous"]
    candidate: ResourceCandidate
    existing_resource: ResearchResource | None = None
    matched_by: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> "DeduplicationResult":
        """确保三态结果不会携带相互矛盾的数据。"""
        if self.status == "existing":
            if self.existing_resource is None or self.matched_by is None:
                raise ValueError("EXISTING 必须提供 existing_resource 和 matched_by")
        elif self.existing_resource is not None or self.matched_by is not None:
            raise ValueError("NEW/AMBIGUOUS 不允许携带 existing_resource 或 matched_by")
        return self


class DiscoverySelection(BaseModel):
    """DiscoveryAgent 只通过本轮 observation ID 选择资源。"""

    model_config = ConfigDict(extra="forbid")

    selected_new_candidate_ids: list[str] = Field(default_factory=list)
    selected_existing_resource_ids: list[str] = Field(default_factory=list)
