"""SciTrace Walking Skeleton 的端到端编排测试。"""

import json
from typing import Any

from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from scitrace.agents import initial_scitrace_state
from scitrace.agents.orchestration import SpecialistRoutingMiddleware
from tests.agents.fakes import (
    SPECIALIST_TOOLS,
    DeterministicSupervisorModel,
    StubWorld,
    build_test_agent,
)


def test_agent_autonomously_completes_stub_reproduction() -> None:
    """真实 Agent loop 应自主形成资源、方案、运行、验证的完整链路。"""
    agent = build_test_agent()
    config = {"configurable": {"thread_id": "walking-skeleton-e2e"}}

    result = agent.invoke(
        initial_scitrace_state(
            task_id="task-walking-skeleton",
            query="Autonomously reproduce the primary result of the supplied paper.",
        ),
        config=config,
    )

    actions = [
        json.loads(str(message.content))["action"]
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    ]
    assert actions == [
        "discovery_result",
        "propose_spec",
        "execution_succeeded",
        "goal_satisfied",
    ]
    assert len(result["resources"]) == 1
    assert result["experiment_spec"] is not None
    assert result["experiment_run"] is not None
    assert result["experiment_run"].experiment_spec_id == result["experiment_spec"].id
    assert result["experiment_run"].status == "succeeded"
    assert result["final_answer"] is not None
    assert isinstance(result["messages"][-1], AIMessage)

    tool_call_ids = {
        call["id"]
        for message in result["messages"]
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert tool_messages
    assert {message.tool_call_id for message in tool_messages} == tool_call_ids

    # 同一个 thread_id 的最终状态应已写入真实 LangGraph checkpointer。
    checkpoint = agent.get_state(config)
    assert checkpoint.values["final_answer"] == result["final_answer"]
    assert checkpoint.values["experiment_run"].id == result["experiment_run"].id
    assert isinstance(checkpoint.values["messages"][-1], AIMessage)


def test_initial_state_contains_only_required_main_state_fields() -> None:
    """初始化结果不应混入预算、结论布尔值或 Specialist 内部过程状态。"""
    state = initial_scitrace_state("task-state", "Reproduce the paper.")

    assert set(state) == {
        "messages",
        "task_id",
        "resources",
        "experiment_spec",
        "experiment_run",
        "required_specialist",
        "final_answer",
    }


def test_compiled_agent_is_a_real_langgraph() -> None:
    """防止 Walking Skeleton 退化为手写的顺序函数调用。"""
    agent = build_test_agent()

    graph = agent.get_graph()

    assert "model" in graph.nodes
    assert "tools" in graph.nodes


def test_need_resources_world_returns_to_discovery() -> None:
    """确定性模型用于证明 NeedResources 测试世界和 Command 回写机制正确。"""
    agent = build_test_agent()
    result = agent.invoke(
        initial_scitrace_state("task-need-resources", "Reproduce the paper."),
        config={"configurable": {"thread_id": "need-resources-mechanism"}},
        context=StubWorld(scenario="need_resources"),
    )

    actions = [
        json.loads(str(message.content))["action"]
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    ]
    assert actions == [
        "discovery_result",
        "need_resources",
        "discovery_result",
        "propose_spec",
        "execution_succeeded",
        "goal_satisfied",
    ]
    assert {resource.kind for resource in result["resources"]} == {"paper", "repository"}

    discovery_observations = [
        json.loads(str(message.content))
        for message in result["messages"]
        if isinstance(message, ToolMessage)
        and json.loads(str(message.content)).get("action") == "discovery_result"
    ]
    assert discovery_observations[0]["summary"]["paper_count"] == 1
    assert discovery_observations[1]["summary"]["paper_count"] == 0
    assert discovery_observations[1]["summary"]["repository_count"] == 1


def test_required_specialist_is_enforced_by_middleware() -> None:
    """Middleware 只落实已有 constraint，同时过滤工具并强制 tool_choice。"""
    captured: dict[str, Any] = {}

    def handler(request: ModelRequest) -> ModelResponse:
        captured["tools"] = request.tools
        captured["tool_choice"] = request.tool_choice
        return ModelResponse(result=[AIMessage(content="")])

    request = ModelRequest(
        model=DeterministicSupervisorModel(),
        messages=[],
        tools=list(SPECIALIST_TOOLS),
        state={"required_specialist": "analysis"},
    )

    SpecialistRoutingMiddleware().wrap_model_call(request, handler)

    assert [tool.name for tool in captured["tools"]] == ["analysis_agent"]
    assert captured["tool_choice"] == "analysis_agent"
