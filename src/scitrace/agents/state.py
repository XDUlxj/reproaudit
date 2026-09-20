"""SciTrace 主 Agent 的最小运行时状态。"""

from typing import Literal

from langgraph.graph import MessagesState

from scitrace.models import ExperimentRun, ExperimentSpec, ResearchResource


class SciTraceState(MessagesState):
    """跨 Specialist 共享的当前事实、编排约束与 graph 输出。"""

    task_id: str
    resources: list[ResearchResource]
    experiment_spec: ExperimentSpec | None
    experiment_run: ExperimentRun | None
    required_specialist: Literal["discovery", "analysis", "execution"] | None
    final_answer: str | None
