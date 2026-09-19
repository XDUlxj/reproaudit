"""实验方案及验证判据的领域模型。"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from scitrace.models.base import Record


class MetricCriterion(BaseModel):
    """标量指标的确定性复现判据。"""

    kind: Literal["metric"] = "metric"
    name: str = Field(min_length=1)
    reference_value: float
    operator: Literal["approximately_equal", "greater_or_equal", "less_or_equal"]
    tolerance: float = Field(default=0.0, ge=0.0)


class ArtifactCriterion(BaseModel):
    """实验产物的验证判据。"""

    kind: Literal["artifact"] = "artifact"
    name: str = Field(min_length=1)
    verifier: Literal["existence", "structured", "semantic"]
    requirement: str = Field(min_length=1)


VerificationCriterion = Annotated[
    MetricCriterion | ArtifactCriterion,
    Field(discriminator="kind"),
]


class OutputRequirement(BaseModel):
    """ExecutionAgent 必须收集的输出；不等同于验证成功。"""

    kind: Literal["metric", "artifact"]
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ExperimentSpec(Record):
    """经 Policy/HITL 接受并可实际执行的正式实验方案。"""

    goal: str = Field(min_length=1)
    resource_ids: list[str] = Field(default_factory=list)
    commands: list[str] = Field(min_length=1)
    verification_criteria: list[VerificationCriterion] = Field(default_factory=list)
    parent_spec_id: str | None = None
