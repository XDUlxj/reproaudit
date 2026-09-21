"""Discovery tools 与去重层之间的运行时数据契约，不属于持久化 Entity。"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from scitrace.models.resource import ResearchResource


class ExistingResourceMatch(BaseModel):
    """Candidate 通过强身份标识匹配到的已存在资源。"""

    resource: ResearchResource
    matched_by: str
    discovered_locations: list[dict[str, Any]] = Field(default_factory=list)


class SearchObservation(BaseModel):
    """Search/Resolve 的标准化三态观察，任何 Candidate 都不会静默消失。"""

    new_candidates: list[dict[str, Any]] = Field(default_factory=list)
    existing_resources: list[ExistingResourceMatch] = Field(default_factory=list)
    ambiguous_candidates: list[dict[str, Any]] = Field(default_factory=list)


class DeduplicationResult(BaseModel):
    """ResourceService 对单个 Candidate 的确定性身份判断。"""

    status: Literal["new", "existing", "ambiguous"]
    candidate: dict[str, Any]
    existing_resource: ResearchResource | None = None
    matched_by: str | None = None
