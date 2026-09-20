"""Specialist Agent 与主编排之间的结构化结果契约。"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from scitrace.models import ObservedOutput, ResearchResource, VerificationCriterion


class ResourceSummary(BaseModel):
    paper_count: int = 0
    repository_count: int = 0
    dataset_count: int = 0
    model_count: int = 0


class DiscoveryResult(BaseModel):
    discovered_resources: list[ResearchResource] = Field(default_factory=list)
    summary: ResourceSummary


class ResourceRequirement(BaseModel):
    kind: Literal["paper", "repository", "dataset", "model"]
    description: str


class ExperimentSpecDraft(BaseModel):
    goal: str
    resource_ids: list[str] = Field(default_factory=list)
    commands: list[str] = Field(min_length=1)
    verification_criteria: list[VerificationCriterion] = Field(default_factory=list)


class ExperimentSpecProposal(BaseModel):
    spec: ExperimentSpecDraft
    rationale: str


class NeedResources(BaseModel):
    action: Literal["need_resources"] = "need_resources"
    missing: list[ResourceRequirement]
    summary: str


class ProposeSpec(BaseModel):
    action: Literal["propose_spec"] = "propose_spec"
    proposal: ExperimentSpecProposal
    summary: str


class KeepSpec(BaseModel):
    action: Literal["keep_spec"] = "keep_spec"
    summary: str


class GoalSatisfied(BaseModel):
    action: Literal["goal_satisfied"] = "goal_satisfied"
    summary: str


class UnableToResolve(BaseModel):
    action: Literal["unable_to_resolve"] = "unable_to_resolve"
    summary: str


AnalysisResult = Annotated[
    NeedResources | ProposeSpec | KeepSpec | GoalSatisfied | UnableToResolve,
    Field(discriminator="action"),
]


class ExecutionSucceeded(BaseModel):
    status: Literal["succeeded"] = "succeeded"
    experiment_run_id: str
    outputs: list[ObservedOutput] = Field(default_factory=list)


class ExecutionFailed(BaseModel):
    status: Literal["failed"] = "failed"
    experiment_run_id: str
    outputs: list[ObservedOutput] = Field(default_factory=list)
    error: str


class ExecutionInterrupted(BaseModel):
    status: Literal["interrupted"] = "interrupted"
    experiment_run_id: str
    outputs: list[ObservedOutput] = Field(default_factory=list)
    summary: str


ExecutionResult = Annotated[
    ExecutionSucceeded | ExecutionFailed | ExecutionInterrupted,
    Field(discriminator="status"),
]
