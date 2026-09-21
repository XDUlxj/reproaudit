"""真实 GLM + deterministic Specialist Stub 的 Supervisor Routing E2E。"""

import json
import os
import time
from collections import Counter
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from scitrace.agents import (
    build_discovery_agent,
    build_discovery_agent_tool,
    build_glm_model,
    build_scitrace_agent,
    initial_scitrace_state,
)
from scitrace.models import PaperResource
from scitrace.models.discovery import SearchObservation
from scitrace.services import ResourceAdmissionService, ResourceService
from tests.agents.fake_discovery_tools import (
    DiscoveryToolRecorder,
    FakeResourceVerifier,
    InMemoryResourceRepository,
    build_fake_discovery_tools,
)
from tests.agents.fakes import (
    StubWorld,
    analysis_agent_tool,
    build_test_agent,
    execution_agent_tool,
)


@pytest.mark.integration
@pytest.mark.parametrize(
    (
        "case_name",
        "delegated_request",
        "confirmed",
        "expected_kinds",
        "required_tools",
    ),
    [
        (
            "paper_only",
            'Find the paper "ZIPIT! Merging Models from Different Tasks without Training".',
            [],
            {"paper"},
            {"search_papers"},
        ),
        (
            "paper_and_repository",
            "Find both required resources for ZIPIT: (1) the paper and (2) its repository.",
            [],
            {"paper", "repository"},
            {"search_papers", "search_repositories"},
        ),
        (
            "repository_with_existing_paper",
            "Find the repository required for the already confirmed ZIPIT paper.",
            [
                {
                    "id": "paper-zipit",
                    "kind": "paper",
                    "name": "ZIPIT! Merging Models from Different Tasks without Training",
                }
            ],
            {"repository"},
            {"search_repositories"},
        ),
        (
            "dataset_only",
            "Find the CIFAR-10 dataset resource.",
            [],
            {"dataset"},
            {"search_datasets"},
        ),
        (
            "model_only",
            "Find the ZIPIT model checkpoint resource.",
            [],
            {"model"},
            {"search_models"},
        ),
        (
            "all_four_resource_types",
            "Find all four requested resources for this task: the ZIPIT paper, its repository, "
            "the CIFAR-10 dataset, and the ZIPIT model checkpoint.",
            [],
            {"paper", "repository", "dataset", "model"},
            {"search_papers", "search_repositories", "search_datasets", "search_models"},
        ),
    ],
)
def test_real_discovery_agent_v1_autonomously_searches(
    case_name: str,
    delegated_request: str,
    confirmed: list[dict[str, str]],
    expected_kinds: set[str],
    required_tools: set[str],
) -> None:
    """V2 只给能力与边界，由真实 DiscoveryAgent 自主选择 Search Tools。"""
    _require_real_glm()
    recorder = DiscoveryToolRecorder()
    resource_service = ResourceService()
    verifier = FakeResourceVerifier()
    admission = ResourceAdmissionService(
        resource_service=resource_service,
        verifier=verifier,
        repository=InMemoryResourceRepository(resource_service),
    )
    agent = build_discovery_agent(
        model=build_glm_model(),
        discovery_tools=build_fake_discovery_tools(recorder),
        resource_service=resource_service,
    )
    instruction = (
        f"Delegated request:\n{delegated_request}\n\n"
        "Resources already confirmed before this invocation:\n"
        f"{json.dumps(confirmed, ensure_ascii=False)}"
    )

    started_at = time.perf_counter()
    result = agent.invoke({"messages": [HumanMessage(content=instruction)]})
    latency_seconds = time.perf_counter() - started_at
    selection = result["structured_response"]
    observations = [
        SearchObservation.model_validate_json(str(message.content))
        for message in result["messages"]
        if isinstance(message, ToolMessage) and (message.name or "").startswith("search_")
    ]
    observed_new = [
        candidate
        for observation in observations
        for candidate in observation.new_candidates
    ]
    observed_existing_ids = {
        match.resource.id
        for observation in observations
        for match in observation.existing_resources
    }
    parent_resources = (
        [
            PaperResource(
                id="paper-zipit",
                name="ZIPIT! Merging Models from Different Tasks without Training",
                arxiv_id="2305.03053",
            )
        ]
        if confirmed
        else []
    )
    discovery_result = admission.admit(
        selection,
        parent_resources=parent_resources,
        observed_new_candidates=observed_new,
        observed_existing_resource_ids=observed_existing_ids,
        task_id="task-discovery-eval",
    )
    returned_kinds = {resource.kind for resource in discovery_result.discovered_resources}
    returned_ids = {resource.id for resource in discovery_result.discovered_resources}
    supported_ids = {resource.id for resource in discovery_result.discovered_resources}
    tool_counts = Counter(call["tool"] for call in recorder.calls)
    tool_calls_per_round = [
        len(message.tool_calls)
        for message in result["messages"]
        if isinstance(message, AIMessage) and message.tool_calls
    ]
    search_call_ids = {
        call["id"]
        for message in result["messages"]
        if isinstance(message, AIMessage)
        for call in message.tool_calls
        if call["name"].startswith("search_")
    }
    search_result_ids = {
        message.tool_call_id
        for message in result["messages"]
        if isinstance(message, ToolMessage) and (message.name or "").startswith("search_")
    }
    trace = {
        "case": case_name,
        "tool_calls": recorder.calls,
        "tool_call_count": dict(tool_counts),
        "repeated_tool_call_count": sum(max(0, count - 1) for count in tool_counts.values()),
        "tool_calls_per_round": tool_calls_per_round,
        "max_parallel_tool_calls": max(tool_calls_per_round, default=0),
        "returned_resource_types": sorted(returned_kinds),
        "duplicate_existing_resources": sorted(
            returned_ids & {resource["id"] for resource in confirmed}
        ),
        "hallucinated_resources": sorted(returned_ids - supported_ids),
        "discovery_result_valid": True,
        "latency_seconds": round(latency_seconds, 3),
    }
    print(json.dumps(trace, ensure_ascii=False, indent=2))

    assert returned_kinds == expected_kinds
    assert required_tools <= set(tool_counts)
    assert search_result_ids == search_call_ids
    assert trace["duplicate_existing_resources"] == []
    assert trace["hallucinated_resources"] == []


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
    agent = build_test_agent(model=build_glm_model())
    query = (
        "Reproduce the primary accuracy result reported by the paper titled "
        "'Stub Paper for Walking Skeleton'. Locate and verify the required scientific "
        "resources, establish an executable experiment, run it, and report whether the "
        "reported result was reproduced. Do not report success without scientific verification."
    )
    result = agent.invoke(
        initial_scitrace_state(f"task-{run_id}", query),
        config={"configurable": {"thread_id": run_id}, "recursion_limit": 60},
        context=StubWorld(scenario=scenario),
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


@pytest.mark.integration
def test_real_supervisor_and_discovery_agent_complete_nested_tool_loop() -> None:
    """真实 Supervisor 与 DiscoveryAgent 完成自主 Search Agent Loop。"""
    _require_real_glm()
    recorder = DiscoveryToolRecorder()
    resource_service = ResourceService()
    admission = ResourceAdmissionService(
        resource_service=resource_service,
        verifier=FakeResourceVerifier(),
        repository=InMemoryResourceRepository(resource_service),
    )
    discovery_agent = build_discovery_agent(
        model=build_glm_model(),
        discovery_tools=build_fake_discovery_tools(recorder),
        resource_service=resource_service,
        context_schema=StubWorld,
    )
    discovery_tool = build_discovery_agent_tool(discovery_agent, admission)
    agent = build_scitrace_agent(
        model=build_glm_model(),
        specialist_tools=[discovery_tool, analysis_agent_tool, execution_agent_tool],
        context_schema=StubWorld,
    )
    run_id = "real-supervisor-real-discovery"
    result = agent.invoke(
        initial_scitrace_state(
            f"task-{run_id}",
            (
                "Reproduce the primary result from the paper 'ZIPIT! Merging Models from Different "
                "Tasks without Training'. Find and verify the scientific resources needed for a "
                "reproducible experiment, execute the accepted specification, and report success "
                "only after scientific verification."
            ),
        ),
        config={"configurable": {"thread_id": run_id}, "recursion_limit": 60},
        context=StubWorld(scenario="happy_path"),
    )

    print(json.dumps({"discovery_tool_trace": recorder.calls}, ensure_ascii=False, indent=2))
    assert result["resources"]
    assert result["experiment_spec"] is not None
    assert result["experiment_run"] is not None
    assert result["experiment_run"].experiment_spec_id == result["experiment_spec"].id
    assert result["final_answer"] is not None

    tool_names = [call["tool"] for call in recorder.calls]
    assert "search_papers" in tool_names
    assert "search_repositories" in tool_names
    supported_ids = {
        "paper-zipit",
        "repository-zipit",
        "dataset-cifar10",
        "model-zipit-checkpoint",
    }
    assert {resource.id for resource in result["resources"]} <= supported_ids
