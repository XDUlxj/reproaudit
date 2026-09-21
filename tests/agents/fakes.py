"""Walking Skeleton 专用 deterministic Test World；禁止生产代码导入。"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from langchain.messages import ToolMessage
from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import Field

from scitrace.agents import build_scitrace_agent
from scitrace.agents.state import SciTraceState
from scitrace.models import (
    ExperimentRun,
    ExperimentSpec,
    MetricCriterion,
    MetricOutput,
    PaperResource,
    RepositoryResource,
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
    NeedResources,
    ProposeSpec,
    ResourceRequirement,
    ResourceSummary,
)


@dataclass(frozen=True)
class StubWorld:
    """每次测试调用的只读场景配置，不进入 Main State。"""

    scenario: Literal["happy_path", "need_resources"] = "happy_path"


def _merge_resources(
    current: list[ResearchResource], discovered: list[ResearchResource]
) -> list[ResearchResource]:
    by_id = {resource.id: resource for resource in current}
    by_id.update({resource.id: resource for resource in discovered})
    return list(by_id.values())


def _has_tool_action(messages: list[Any], expected_action: str) -> bool:
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            observation = json.loads(str(message.content))
        except json.JSONDecodeError:
            continue
        if isinstance(observation, dict) and observation.get("action") == expected_action:
            return True
    return False


def run_discovery_stub(
    *,
    task_id: str,
    request: str,
    resources: list[ResearchResource],
    scenario: str,
    repository_requested: bool,
) -> DiscoveryResult:
    """按测试世界返回固定资源；request 保留用于委派质量观测。"""
    _ = request
    kinds = {resource.kind for resource in resources}
    discovered: list[ResearchResource] = []
    if "paper" not in kinds:
        discovered.append(
            PaperResource(
                id=f"stub-paper-{task_id}",
                name="Stub Paper for Walking Skeleton",
                locations=[WebLocation(url="https://example.invalid/stub-paper.pdf")],
                metadata={"stub": True},
            )
        )
    elif scenario == "need_resources" and repository_requested and "repository" not in kinds:
        discovered.append(
            RepositoryResource(
                id=f"stub-repository-{task_id}",
                name="Stub Repository for Walking Skeleton",
                locations=[WebLocation(url="https://example.invalid/stub-repository")],
                revision="stub-revision",
                metadata={"stub": True},
            )
        )
    return DiscoveryResult(
        discovered_resources=discovered,
        summary=ResourceSummary(
            paper_count=sum(resource.kind == "paper" for resource in discovered),
            repository_count=sum(resource.kind == "repository" for resource in discovered),
        ),
    )


def run_analysis_stub(
    *,
    resources: list[ResearchResource],
    experiment_run: ExperimentRun | None,
    request: str,
    scenario: str,
) -> AnalysisResult:
    """根据 Test World 固定返回 NeedResources、ProposeSpec 或 GoalSatisfied。"""
    _ = request
    if experiment_run is not None and experiment_run.status == "succeeded":
        return GoalSatisfied(summary="Stub verifier confirms the reproduction criterion is satisfied.")
    if scenario == "need_resources" and not any(
        resource.kind == "repository" for resource in resources
    ):
        return NeedResources(
            missing=[
                ResourceRequirement(
                    kind="repository",
                    description="The confirmed implementation repository for the paper.",
                )
            ],
            summary="A confirmed implementation repository is missing.",
        )
    proposal = ExperimentSpecProposal(
        spec=ExperimentSpecDraft(
            goal="Reproduce the stub paper's primary accuracy result.",
            resource_ids=[resource.id for resource in resources],
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
        rationale="Deterministic proposal for Supervisor routing tests.",
    )
    return ProposeSpec(proposal=proposal, summary="An experiment specification was proposed.")


def run_execution_stub(
    *, experiment_spec: ExperimentSpec, request: str
) -> tuple[ExperimentRun, ExecutionSucceeded]:
    """不启动进程，仅构造结构合法的成功运行。"""
    _ = request
    run = ExperimentRun(
        experiment_spec_id=experiment_spec.id,
        status="succeeded",
        outputs=[MetricOutput(name="accuracy", value=0.925)],
        finished_at=datetime.now(UTC),
    )
    return run, ExecutionSucceeded(experiment_run_id=run.id, outputs=run.outputs)


@tool("discovery_agent")
def discovery_agent_tool(
    request: str,
    runtime: ToolRuntime[StubWorld, SciTraceState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Delegate scientific resource discovery to the Discovery specialist.

    Use this specialist to discover and verify external scientific resources,
    including papers, repositories, datasets, and models. This specialist does
    not design experiments, execute commands, or determine whether a
    reproduction attempt succeeded.
    """
    parent = runtime.state
    scenario = runtime.context.scenario if runtime.context else "happy_path"
    result = run_discovery_stub(
        task_id=parent["task_id"],
        request=request,
        resources=parent["resources"],
        scenario=scenario,
        repository_requested=_has_tool_action(parent["messages"], "need_resources"),
    )
    return Command(
        update={
            "resources": _merge_resources(parent["resources"], result.discovered_resources),
            "required_specialist": None,
            "messages": [
                ToolMessage(
                    tool_call_id=tool_call_id,
                    content=json.dumps(
                        {
                            "action": "discovery_result",
                            "summary": result.summary.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
        }
    )


@tool("analysis_agent")
def analysis_agent_tool(
    request: str,
    runtime: ToolRuntime[StubWorld, SciTraceState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Delegate scientific reasoning to the Analysis specialist.

    Use this specialist to analyze confirmed scientific resources, identify
    missing requirements, construct or revise an experiment specification,
    interpret experiment outputs, and evaluate whether experimental evidence
    satisfies the reproduction goal. This specialist does not execute
    experiment commands or discover external resources directly.
    """
    parent = runtime.state
    scenario = runtime.context.scenario if runtime.context else "happy_path"
    result = run_analysis_stub(
        resources=parent["resources"],
        experiment_run=parent.get("experiment_run"),
        request=request,
        scenario=scenario,
    )
    updates: dict[str, Any] = {"required_specialist": None}
    if isinstance(result, ProposeSpec):
        draft = result.proposal.spec
        updates["experiment_spec"] = ExperimentSpec(
            goal=draft.goal,
            resource_ids=draft.resource_ids,
            commands=draft.commands,
            verification_criteria=draft.verification_criteria,
            parent_spec_id=parent["experiment_spec"].id if parent.get("experiment_spec") else None,
        )
    elif isinstance(result, GoalSatisfied):
        updates["final_answer"] = result.summary

    observation: dict[str, Any] = {"action": result.action, "summary": result.summary}
    if isinstance(result, NeedResources):
        observation["missing"] = [item.model_dump(mode="json") for item in result.missing]
    updates["messages"] = [
        ToolMessage(
            tool_call_id=tool_call_id,
            content=json.dumps(observation, ensure_ascii=False),
        )
    ]
    return Command(update=updates)


@tool("execution_agent")
def execution_agent_tool(
    request: str,
    runtime: ToolRuntime[StubWorld, SciTraceState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Delegate experiment execution to the Execution specialist.

    Use this specialist to execute an existing accepted ExperimentSpec and
    report actual runtime results, outputs, and failures. This specialist does
    not define the scientific goal or determine whether the scientific
    reproduction goal has been satisfied.
    """
    parent = runtime.state
    spec = parent.get("experiment_spec")
    if spec is None:
        raise ValueError("没有正式 ExperimentSpec，禁止调用 Execution specialist")
    selected = {resource.id: resource for resource in parent["resources"]}
    missing_resource_ids = set(spec.resource_ids) - selected.keys()
    if missing_resource_ids:
        missing = ", ".join(sorted(missing_resource_ids))
        raise ValueError(f"ExperimentSpec 引用了未确认的资源：{missing}")
    run, result = run_execution_stub(experiment_spec=spec, request=request)
    return Command(
        update={
            "experiment_run": run,
            "required_specialist": "analysis",
            "messages": [
                ToolMessage(
                    tool_call_id=tool_call_id,
                    content=json.dumps(
                        {
                            "action": "execution_succeeded",
                            "status": result.status,
                            "experiment_run_id": result.experiment_run_id,
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
        }
    )


SPECIALIST_TOOLS: tuple[BaseTool, ...] = (
    discovery_agent_tool,
    analysis_agent_tool,
    execution_agent_tool,
)


class DeterministicSupervisorModel(BaseChatModel):
    """仅用于机制测试的规则型 tool-calling model。"""

    available_tool_names: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def _llm_type(self) -> str:
        return "scitrace-test-supervisor"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        names = tuple(self._tool_name(tool) for tool in tools)
        return self.model_copy(update={"available_tool_names": names})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        observations = [
            self._observation(message) for message in messages if isinstance(message, ToolMessage)
        ]
        last_action = observations[-1].get("action") if observations else None
        routes = {
            None: ("discovery_agent", "Find required resources."),
            "discovery_result": ("analysis_agent", "Analyze confirmed resources."),
            "need_resources": ("discovery_agent", "Find the missing confirmed resource."),
            "propose_spec": ("execution_agent", "Execute the accepted specification."),
            "execution_succeeded": ("analysis_agent", "Verify the experimental evidence."),
        }
        if last_action == "goal_satisfied":
            message = AIMessage(content="Stub reproduction completed and scientifically verified.")
        elif last_action in routes:
            tool_name, request = routes[last_action]
            message = self._delegate(tool_name, request, messages)
        else:
            message = AIMessage(content=f"Unable to continue from action: {last_action}")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _delegate(self, tool_name: str, request: str, messages: list[BaseMessage]) -> AIMessage:
        if tool_name not in self.available_tool_names:
            return AIMessage(content=f"Required specialist tool is unavailable: {tool_name}")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tool_name,
                    "args": {"request": request},
                    "id": f"call-{tool_name}-{len(messages)}",
                }
            ],
        )

    @staticmethod
    def _observation(message: ToolMessage) -> dict[str, Any]:
        try:
            value = json.loads(str(message.content))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _tool_name(tool: dict[str, Any] | type | Any | BaseTool) -> str:
        if isinstance(tool, BaseTool):
            return tool.name
        if isinstance(tool, dict):
            function = tool.get("function", tool)
            return str(function.get("name", ""))
        return str(getattr(tool, "__name__", getattr(tool, "name", "")))


def build_test_agent(
    *,
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """组装只存在于 tests 的 Walking Skeleton。"""
    return build_scitrace_agent(
        model=model or DeterministicSupervisorModel(),
        specialist_tools=SPECIALIST_TOOLS,
        context_schema=StubWorld,
        checkpointer=checkpointer,
    )
