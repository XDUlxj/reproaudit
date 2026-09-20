"""Walking Skeleton 使用的确定性 Specialist stub。"""

from datetime import UTC, datetime

from scitrace.models import (
    ExperimentRun,
    ExperimentSpec,
    MetricCriterion,
    MetricOutput,
    PaperResource,
    ResearchResource,
    WebLocation,
)
from scitrace.models.agent_results import (
    AnalysisResult,
    DiscoveryResult,
    ExecutionSucceeded,
    ExperimentSpecDraft,
    ExperimentSpecProposal,
    GoalSatisfied,
    ProposeSpec,
    ResourceSummary,
)


def run_discovery_stub(*, task_id: str, request: str) -> DiscoveryResult:
    """返回一个固定但结构合法的论文资源。"""
    _ = request
    resource = PaperResource(
        id=f"stub-paper-{task_id}",
        name="Stub Paper for Walking Skeleton",
        locations=[WebLocation(url="https://example.invalid/stub-paper.pdf")],
        metadata={"stub": True},
    )
    return DiscoveryResult(
        discovered_resources=[resource],
        summary=ResourceSummary(paper_count=1),
    )


def run_analysis_stub(
    *,
    resources: list[ResearchResource],
    experiment_run: ExperimentRun | None,
    request: str,
) -> AnalysisResult:
    """第一次提出 Spec；Run 成功后给出科学目标已满足。"""
    _ = request
    if experiment_run is not None and experiment_run.status == "succeeded":
        return GoalSatisfied(summary="Stub verifier confirms the reproduction criterion is satisfied.")

    resource_ids = [resource.id for resource in resources]
    proposal = ExperimentSpecProposal(
        spec=ExperimentSpecDraft(
            goal="Reproduce the stub paper's primary accuracy result.",
            resource_ids=resource_ids,
            commands=["python -m stub_reproduction --evaluate"],
            verification_criteria=[
                MetricCriterion(
                    name="accuracy",
                    reference_value=0.92,
                    operator="greater_or_equal",
                    tolerance=0.01,
                )
            ],
        ),
        rationale="Walking Skeleton uses a deterministic proposal to exercise orchestration.",
    )
    return ProposeSpec(
        proposal=proposal,
        summary="An experiment specification was proposed.",
    )


def run_execution_stub(
    *, experiment_spec: ExperimentSpec, request: str
) -> tuple[ExperimentRun, ExecutionSucceeded]:
    """不启动进程，仅构造一次结构合法的成功运行。"""
    _ = request
    run = ExperimentRun(
        experiment_spec_id=experiment_spec.id,
        status="succeeded",
        outputs=[MetricOutput(name="accuracy", value=0.925)],
        finished_at=datetime.now(UTC),
    )
    return run, ExecutionSucceeded(experiment_run_id=run.id, outputs=run.outputs)
