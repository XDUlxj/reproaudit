"""SciTrace 主 Agent 与 Specialist 的运行时状态。"""

from typing import Literal

from langgraph.graph import MessagesState

from scitrace.models import ExperimentRun, ExperimentSpec, ResearchResource


class SciTraceState(MessagesState):
    """主 Agent 当前工作快照；不是业务历史数据库。"""

    task_id: str
    resources: list[ResearchResource]
    experiment_spec: ExperimentSpec | None
    experiment_run: ExperimentRun | None
    required_specialist: Literal["discovery", "analysis", "execution"] | None
    execution_attempts: int
    goal_satisfied: bool
    final_answer: str | None


class DiscoveryAgentState(MessagesState):
    task_id: str
    resources: list[ResearchResource]
    recovery_count: int


class AnalysisAgentState(MessagesState):
    task_id: str
    resources: list[ResearchResource]
    experiment_spec: ExperimentSpec | None
    experiment_run: ExperimentRun | None
    recovery_count: int


class ExecutionAgentState(MessagesState):
    task_id: str
    resources: list[ResearchResource]
    experiment_spec: ExperimentSpec
    experiment_run: ExperimentRun | None
    recovery_count: int
