"""Walking Skeleton 使用的确定性 Specialist stub。"""

from datetime import UTC, datetime

from scitrace.agents.state import AnalysisAgentState, DiscoveryAgentState, ExecutionAgentState
from scitrace.models import (
    ExperimentRun,
    MetricCriterion,
    MetricOutput,
    PaperResource,
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


def run_discovery_stub(state: DiscoveryAgentState) -> DiscoveryResult:
    """返回一个固定但结构合法的论文资源。"""
    resource = PaperResource(
        id=f"stub-paper-{state['task_id']}",
        name="Stub Paper for Walking Skeleton",
        locations=[WebLocation(url="https://example.invalid/stub-paper.pdf")],
        metadata={"stub": True},
    )
    return DiscoveryResult(
        discovered_resources=[resource],
        summary=ResourceSummary(paper_count=1),
    )


def run_analysis_stub(state: AnalysisAgentState) -> AnalysisResult:
    """第一次提出 Spec；Run 成功后给出科学目标已满足。"""
    run = state.get("experiment_run")
    if run is not None and run.status == "succeeded":
        return GoalSatisfied(summary="Stub verifier confirms the reproduction criterion is satisfied.")

    resource_ids = [resource.id for resource in state["resources"]]
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
        summary="A formal experiment specification can be materialized from the stub proposal.",
    )


def run_execution_stub(state: ExecutionAgentState) -> tuple[ExperimentRun, ExecutionSucceeded]:
    """不启动进程，仅构造一次结构合法的成功运行。"""
    run = ExperimentRun(
        experiment_spec_id=state["experiment_spec"].id,
        status="succeeded",
        outputs=[MetricOutput(name="accuracy", value=0.925)],
        finished_at=datetime.now(UTC),
    )
    return run, ExecutionSucceeded(experiment_run_id=run.id, outputs=run.outputs)
