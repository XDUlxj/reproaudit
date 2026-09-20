"""SciTrace Walking Skeleton 的真实 LangChain/LangGraph 编排。"""

import json
from collections.abc import Callable
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from scitrace.agents.state import (
    AnalysisAgentState,
    DiscoveryAgentState,
    ExecutionAgentState,
    SciTraceState,
)
from scitrace.agents.stubs import run_analysis_stub, run_discovery_stub, run_execution_stub
from scitrace.agents.testing_model import WalkingSkeletonSupervisorModel
from scitrace.models import ExperimentSpec, ResearchResource
from scitrace.models.agent_results import GoalSatisfied, ProposeSpec


def _merge_resources(
    current: list[ResearchResource], discovered: list[ResearchResource]
) -> list[ResearchResource]:
    by_id = {resource.id: resource for resource in current}
    by_id.update({resource.id: resource for resource in discovered})
    return list(by_id.values())


@tool("discovery_agent")
def discovery_agent_tool(
    request: str,
    runtime: ToolRuntime[SciTraceState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """委派 Discovery specialist，发现并验证科研资源。"""
    parent = runtime.state
    child_state: DiscoveryAgentState = {
        "task_id": parent["task_id"],
        "resources": parent["resources"],
        "recovery_count": 0,
        "messages": [HumanMessage(content=request)],
    }
    result = run_discovery_stub(child_state)
    next_required = "analysis" if parent.get("required_specialist") == "discovery" else None
    return Command(
        update={
            "resources": _merge_resources(parent["resources"], result.discovered_resources),
            "required_specialist": next_required,
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
    runtime: ToolRuntime[SciTraceState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """委派 Analysis specialist，提出方案或验证实验结果。"""
    parent = runtime.state
    child_state: AnalysisAgentState = {
        "task_id": parent["task_id"],
        "resources": parent["resources"],
        "experiment_spec": parent.get("experiment_spec"),
        "experiment_run": parent.get("experiment_run"),
        "recovery_count": 0,
        "messages": [HumanMessage(content=request)],
    }
    result = run_analysis_stub(child_state)
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
        updates["goal_satisfied"] = True
        updates["final_answer"] = result.summary

    updates["messages"] = [
        ToolMessage(
            tool_call_id=tool_call_id,
            content=json.dumps(
                {"action": result.action, "summary": result.summary},
                ensure_ascii=False,
            ),
        )
    ]
    return Command(update=updates)


@tool("execution_agent")
def execution_agent_tool(
    request: str,
    runtime: ToolRuntime[SciTraceState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """委派 Execution specialist，执行已正式采用的 ExperimentSpec。"""
    parent = runtime.state
    spec = parent.get("experiment_spec")
    if spec is None:
        raise ValueError("没有正式 ExperimentSpec，禁止调用 Execution specialist")
    selected = {resource.id: resource for resource in parent["resources"]}
    child_state: ExecutionAgentState = {
        "task_id": parent["task_id"],
        "resources": [selected[resource_id] for resource_id in spec.resource_ids],
        "experiment_spec": spec,
        "experiment_run": parent.get("experiment_run"),
        "recovery_count": parent.get("execution_attempts", 0),
        "messages": [HumanMessage(content=request)],
    }
    run, result = run_execution_stub(child_state)
    return Command(
        update={
            "experiment_run": run,
            "execution_attempts": parent.get("execution_attempts", 0) + 1,
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


class SpecialistRoutingMiddleware(AgentMiddleware):
    """有明确路由义务时，只向模型暴露对应 Specialist tool。"""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        required = request.state.get("required_specialist")
        if required is None:
            return handler(request)
        expected_name = f"{required}_agent"
        tools = [candidate for candidate in request.tools if candidate.name == expected_name]
        if len(tools) != 1:
            raise RuntimeError(f"找不到 required specialist tool：{expected_name}")
        return handler(request.override(tools=tools))


SCITRACE_SYSTEM_PROMPT = """You are SciTraceAgent, an autonomous scientific reproduction supervisor.
Use specialist tools based on the current evidence. Discovery finds resources, Analysis proposes or
verifies a specification, and Execution performs an accepted specification. Do not claim success
until Analysis confirms the reproduction criterion after an ExperimentRun.
"""


def _walking_skeleton_checkpointer() -> InMemorySaver:
    """显式允许 checkpoint 中出现的领域模型，避免依赖宽松反序列化默认值。"""
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("scitrace.models.resource", "PaperResource"),
            ("scitrace.models.experiment", "ExperimentSpec"),
            ("scitrace.models.execution", "ExperimentRun"),
            ("scitrace.models.execution", "MetricOutput"),
        ]
    )
    return InMemorySaver(serde=serde)


def build_walking_skeleton_agent(
    *,
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """构造真实 create_agent 图；默认业务能力和模型均为可测试 stub。"""
    return create_agent(
        model=model or WalkingSkeletonSupervisorModel(),
        tools=list(SPECIALIST_TOOLS),
        middleware=[SpecialistRoutingMiddleware()],
        state_schema=SciTraceState,
        checkpointer=checkpointer or _walking_skeleton_checkpointer(),
        system_prompt=SCITRACE_SYSTEM_PROMPT,
        name="scitrace_agent",
    )


def initial_scitrace_state(task_id: str, query: str) -> SciTraceState:
    """创建一次 Walking Skeleton 调用所需的主状态。"""
    return {
        "messages": [HumanMessage(content=query)],
        "task_id": task_id,
        "resources": [],
        "experiment_spec": None,
        "experiment_run": None,
        "required_specialist": None,
        "execution_attempts": 0,
        "goal_satisfied": False,
        "final_answer": None,
    }
