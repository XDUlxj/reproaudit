"""真实 GLM + deterministic Specialist Stub 的 Supervisor Routing E2E。"""

import json
import os
from collections import Counter
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from scitrace.agents import (
    SciTraceContext,
    build_glm_model,
    build_walking_skeleton_agent,
    initial_scitrace_state,
)


def _require_real_glm() -> None:
    if os.getenv("SCITRACE_RUN_GLM_INTEGRATION") != "1":
        pytest.skip("设置 SCITRACE_RUN_GLM_INTEGRATION=1 后才调用真实 GLM API")


def _inspect_trajectory(messages: list[Any], minimum_calls: dict[str, int]) -> dict[str, Any]:
    """提取完整轨迹，并从消息顺序检查前置条件和科学验证约束。"""
    trajectory: list[dict[str, Any]] = []
    calls_by_id: dict[str, str] = {}
    counts: Counter[str] = Counter()
    invalid_calls: list[str] = []
    has_resource = False
    has_spec = False
    verification_required = False
    scientifically_verified = False

    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                tool_name = call["name"]
                calls_by_id[call["id"]] = tool_name
                counts[tool_name] += 1
                if tool_name == "analysis_agent" and not has_resource:
                    invalid_calls.append("analysis_agent called before any confirmed resource")
                if tool_name == "execution_agent" and not has_spec:
                    invalid_calls.append("execution_agent called before ExperimentSpec")
                if verification_required and tool_name != "analysis_agent":
                    invalid_calls.append(f"{tool_name} called while Analysis verification was required")
                trajectory.append(
                    {
                        "event": "specialist_call",
                        "tool": tool_name,
                        "request": call["args"].get("request"),
                        "tool_call_id": call["id"],
                    }
                )
        elif isinstance(message, ToolMessage):
            assert message.tool_call_id in calls_by_id
            result = json.loads(str(message.content))
            action = result.get("action")
            if action == "discovery_result":
                has_resource = True
            elif action == "propose_spec":
                has_spec = True
            elif action == "execution_succeeded":
                verification_required = True
            elif action == "goal_satisfied":
                verification_required = False
                scientifically_verified = True
            trajectory.append(
                {
                    "event": "tool_result",
                    "tool": calls_by_id[message.tool_call_id],
                    "result": result,
                    "tool_call_id": message.tool_call_id,
                }
            )

    redundant_calls = {
        tool: max(0, counts[tool] - minimum)
        for tool, minimum in minimum_calls.items()
    }
    return {
        "trajectory": trajectory,
        "specialist_call_count": dict(counts),
        "redundant_call_count": redundant_calls,
        "invalid_calls": invalid_calls,
        "scientifically_verified": scientifically_verified,
    }


def _run_real_scenario(*, run_id: str, scenario: str) -> tuple[dict[str, Any], dict[str, Any]]:
    agent = build_walking_skeleton_agent(model=build_glm_model())
    query = (
        "Reproduce the primary accuracy result reported by the paper titled "
        "'Stub Paper for Walking Skeleton'. Locate and verify the required scientific "
        "resources, establish an executable experiment, run it, and report whether the "
        "reported result was reproduced. Do not report success without scientific verification."
    )
    result = agent.invoke(
        initial_scitrace_state(f"task-{run_id}", query),
        config={"configurable": {"thread_id": run_id}, "recursion_limit": 60},
        context=SciTraceContext(stub_scenario=scenario),
    )
    checkpoint = agent.get_state({"configurable": {"thread_id": run_id}})
    return result, checkpoint.values


def _assert_completion_invariants(result: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    assert result["resources"]
    assert result["experiment_spec"] is not None
    assert set(result["experiment_spec"].resource_ids) <= {
        resource.id for resource in result["resources"]
    }
    assert result["experiment_run"] is not None
    assert result["experiment_run"].experiment_spec_id == result["experiment_spec"].id
    assert result["experiment_run"].status == "succeeded"
    assert result["final_answer"] is not None
    assert isinstance(result["messages"][-1], AIMessage)
    assert not result["messages"][-1].tool_calls
    assert checkpoint["final_answer"] == result["final_answer"]
    assert checkpoint["experiment_run"].id == result["experiment_run"].id


@pytest.mark.integration
@pytest.mark.parametrize("run_index", range(1, 4))
def test_real_glm_completes_happy_path(run_index: int) -> None:
    """不规定唯一轨迹，只以科研复现闭环不变量判定成功。"""
    _require_real_glm()
    run_id = f"real-glm-happy-path-{run_index}"

    result, checkpoint = _run_real_scenario(run_id=run_id, scenario="happy_path")
    trace = _inspect_trajectory(
        result["messages"],
        minimum_calls={"discovery_agent": 1, "analysis_agent": 2, "execution_agent": 1},
    )
    print(json.dumps({"run_id": run_id, **trace}, ensure_ascii=False, indent=2))

    _assert_completion_invariants(result, checkpoint)
    assert trace["scientifically_verified"] is True
    assert trace["invalid_calls"] == []


@pytest.mark.integration
def test_real_glm_routes_back_to_discovery_for_missing_repository() -> None:
    """Analysis 的 NeedResources 应促使 Supervisor 非线性回到 Discovery。"""
    _require_real_glm()
    run_id = "real-glm-need-resources"

    result, checkpoint = _run_real_scenario(run_id=run_id, scenario="need_resources")
    trace = _inspect_trajectory(
        result["messages"],
        minimum_calls={"discovery_agent": 2, "analysis_agent": 3, "execution_agent": 1},
    )
    print(json.dumps({"run_id": run_id, **trace}, ensure_ascii=False, indent=2))

    _assert_completion_invariants(result, checkpoint)
    assert {resource.kind for resource in result["resources"]} >= {"paper", "repository"}
    actions = [
        event["result"]["action"]
        for event in trace["trajectory"]
        if event["event"] == "tool_result"
    ]
    need_index = actions.index("need_resources")
    assert "discovery_result" in actions[need_index + 1 :]
    assert trace["scientifically_verified"] is True
    assert trace["invalid_calls"] == []
