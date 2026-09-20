"""真实 GLM + SciTrace Walking Skeleton 集成测试。"""

import json
import os

import pytest
from langchain_core.messages import ToolMessage

from scitrace.agents import (
    build_glm_model,
    build_walking_skeleton_agent,
    initial_scitrace_state,
)


@pytest.mark.integration
def test_real_glm_completes_walking_skeleton() -> None:
    """真实模型应自主调用全部 Specialist stub 并形成最终答案。"""
    if os.getenv("SCITRACE_RUN_GLM_INTEGRATION") != "1":
        pytest.skip("设置 SCITRACE_RUN_GLM_INTEGRATION=1 后才调用真实 GLM API")

    agent = build_walking_skeleton_agent(model=build_glm_model())
    config = {"configurable": {"thread_id": "real-glm-walking-skeleton"}}
    state = initial_scitrace_state(
        "task-real-glm-walking-skeleton",
        (
            "This is the SciTrace Walking Skeleton validation. Autonomously reproduce the "
            "paper's primary result by using the available specialist tools and do not stop "
            "before post-execution analysis verification."
        ),
    )
    # 本测试已知入口必须先做资源发现；后续义务由各 Tool result 驱动。
    state["required_specialist"] = "discovery"
    result = agent.invoke(state, config=config)

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
    assert result["experiment_run"].status == "succeeded"
    assert result["final_answer"]
