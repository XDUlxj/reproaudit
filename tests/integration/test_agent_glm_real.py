"""真实 GLM + SciTrace Walking Skeleton 集成测试。"""

import json
import os

import pytest
from langchain_core.messages import AIMessage

from scitrace.agents import (
    build_glm_model,
    build_walking_skeleton_agent,
    initial_scitrace_state,
)


@pytest.mark.integration
@pytest.mark.parametrize("run_index", range(1, 4))
def test_real_glm_completes_walking_skeleton(run_index: int) -> None:
    """真实模型应自主调用全部 Specialist stub 并形成最终答案。"""
    if os.getenv("SCITRACE_RUN_GLM_INTEGRATION") != "1":
        pytest.skip("设置 SCITRACE_RUN_GLM_INTEGRATION=1 后才调用真实 GLM API")

    agent = build_walking_skeleton_agent(model=build_glm_model())
    run_id = f"real-glm-walking-skeleton-{run_index}"
    config = {"configurable": {"thread_id": run_id}}
    result = agent.invoke(
        initial_scitrace_state(
            f"task-{run_id}",
            (
                "Reproduce the primary accuracy result reported by the paper titled "
                "'Stub Paper for Walking Skeleton'. Locate and verify the required scientific "
                "resources, establish an executable experiment, run it, and report whether the "
                "reported result was reproduced. Do not report success without scientific "
                "verification."
            ),
        ),
        config=config,
    )

    routing_trace = [
        {"tool": call["name"], "args": call["args"]}
        for message in result["messages"]
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]
    print(f"Routing Trace #{run_index}:")
    print(json.dumps(routing_trace, ensure_ascii=False, indent=2))
    final_model_text = next(
        (
            str(message.content)
            for message in reversed(result["messages"])
            if isinstance(message, AIMessage) and message.content
        ),
        "",
    )
    print(f"Final Model Response #{run_index}:\n{final_model_text}")

    # 真实 routing 允许合理的重复调用，不把某一条唯一序列当作正确答案。
    assert result["resources"]
    assert result["experiment_spec"] is not None
    assert result["experiment_run"] is not None
    assert result["experiment_run"].experiment_spec_id == result["experiment_spec"].id
    assert result["experiment_run"].status == "succeeded"
    assert result["final_answer"] is not None
    assert routing_trace
