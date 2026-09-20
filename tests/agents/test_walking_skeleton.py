"""SciTrace Walking Skeleton 的端到端编排测试。"""

import json

from langchain_core.messages import AIMessage, ToolMessage

from scitrace.agents import build_walking_skeleton_agent, initial_scitrace_state


def test_agent_autonomously_completes_stub_reproduction() -> None:
    """真实 Agent loop 应自主形成资源、方案、运行、验证的完整链路。"""
    agent = build_walking_skeleton_agent()
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

    # 同一个 thread_id 的最终状态应已写入真实 LangGraph checkpointer。
    checkpoint = agent.get_state(config)
    assert checkpoint.values["final_answer"] == result["final_answer"]
    assert checkpoint.values["experiment_run"].id == result["experiment_run"].id


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
    agent = build_walking_skeleton_agent()

    graph = agent.get_graph()

    assert "model" in graph.nodes
    assert "tools" in graph.nodes
