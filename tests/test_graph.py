from conftest import ScriptedModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from scitrace.config import Settings
from scitrace.graph.builder import build_graph
from scitrace.runtime import Runtime


def runtime(tmp_path, store, actions):
    return Runtime(
        Settings(_env_file=None, artifact_root=tmp_path, glm_api_key="test"),
        store,
        "task",
        model=ScriptedModel(actions),
        index=object(),
    )


def test_simple_question_no_specialists(tmp_path, store):
    r = runtime(
        tmp_path,
        store,
        [("paper_resolve", {"source": "1607.01759"}), ("finish", {"answer": "论文已定位"})],
    )
    graph = build_graph(r, InMemorySaver())
    result = graph.invoke(
        {"task_id": "task", "user_query": "定位论文"}, {"configurable": {"thread_id": "task"}}
    )
    assert result["status"] == "finished"
    assert [o["tool"] for o in result["observations"]] == ["paper_resolve"]
    assert not store.find("execution")


def test_discovery_only_then_finish(tmp_path, store):
    r = runtime(
        tmp_path,
        store,
        [
            ("discovery_agent", {"goal": "寻找代码"}),
            (
                "finish",
                {"discovery_status": "not_found", "missing_resources": ["official repository"]},
            ),
            ("finish", {"answer": "未找到官方实现"}),
        ],
    )
    result = build_graph(r, InMemorySaver()).invoke(
        {"user_query": "找代码"}, {"configurable": {"thread_id": "task"}}
    )
    assert [o["tool"] for o in result["observations"]] == ["discovery_agent"]
    assert not store.find("execution")


def test_approval_restart_and_rejection_replan(tmp_path, store):
    r = runtime(
        tmp_path,
        store,
        [("trace_agent", {"goal": "index r"}), ("index_repository", {"resource_id": "r"})],
    )
    store.put(
        "resource", {"id": "r", "resource_status": "third_party", "url": "https://github.com/a/b"}
    )
    saver = InMemorySaver()
    cfg = {"configurable": {"thread_id": "task"}}
    graph = build_graph(r, saver)
    result = graph.invoke({"user_query": "追踪 Claim"}, cfg)
    assert result["pending_approval"]
    record = store.get("approval", result["pending_approval"])
    record["user_decision"] = "rejected"
    store.put("approval", record)
    r2 = runtime(
        tmp_path,
        store,
        [
            ("trace_agent", {"goal": "paper-only evidence"}),
            ("finish", {"mode": "paper_only", "missing_information": ["code"]}),
            ("finish", {"answer": "提供 paper-only 评估"}),
        ],
    )
    resumed = build_graph(r2, saver).invoke(Command(resume=True), cfg)
    assert resumed["status"] == "finished"
    assert not store.find("execution")
    assert store.find("trace")[0]["mode"] == "paper_only"


def test_existing_plan_direct_execution_specialist(tmp_path, store):
    store.put("plan", {"id": "p"}, "task")
    r = runtime(
        tmp_path,
        store,
        [
            ("execution_agent", {"goal": "执行计划 p"}),
            ("finish", {"status": "blocked", "blockers": ["环境不可用"]}),
            ("finish", {"answer": "执行受阻"}),
        ],
    )
    result = build_graph(r, InMemorySaver()).invoke(
        {"user_query": "执行计划 p"}, {"configurable": {"thread_id": "task"}}
    )
    assert [o["tool"] for o in result["observations"]] == ["execution_agent"]
    assert result["status"] == "partial"


def test_execution_without_plan_cannot_finish_successfully(tmp_path, store):
    r = runtime(
        tmp_path,
        store,
        [
            ("execution_agent", {"goal": "执行实验"}),
            ("finish", {"answer": "内存不足，编译失败，必须升级机器"}),
        ],
    )
    result = build_graph(r, InMemorySaver()).invoke(
        {"user_query": "复现实验"}, {"configurable": {"thread_id": "task"}}
    )
    assert result["status"] == "partial"
    assert "实验尚未开始" in result["final_answer"]
    assert "必须升级机器" not in result["final_answer"]
    assert "没有持久化复现计划" in result["messages"][-2].content
    assert not store.find("agent_loop")


def test_required_execution_rejects_premature_finish(tmp_path, store):
    store.put("plan", {"id": "p", "blockers": []}, "task")
    r = runtime(
        tmp_path,
        store,
        [
            ("finish", {"answer": "已经完成实验"}),
            ("execution_agent", {"goal": "执行 p"}),
            ("finish", {"status": "blocked", "blockers": ["测试中不执行"]}),
            ("finish", {"answer": "机器内存不足"}),
        ],
    )
    result = build_graph(r, InMemorySaver()).invoke(
        {"user_query": "全链路", "requires_execution": True},
        {"configurable": {"thread_id": "task"}},
    )
    assert result["finish_corrections"] == 1
    assert result["status"] == "partial"
    assert result["final_answer"].startswith("实验尚未开始")


def test_successful_ledger_finishes_without_more_model_or_execution(tmp_path, store):
    from scitrace.models.core import ExecutionResult, VerificationResult

    r = runtime(tmp_path, store, [])
    execution = ExecutionResult(
        plan_id="p", plan_hash="hash", status="success", metrics={"P@1": 0.13}
    )
    store.put("execution", execution, "task")
    store.put(
        "verification",
        VerificationResult(
            execution_id=execution.id,
            status="not_tested",
            provenance="assisted",
            reason="教程不验证论文 benchmark",
            assessment="教程完成",
        ),
        "task",
    )
    result = build_graph(r, InMemorySaver()).invoke(
        {"requires_execution": True}, {"configurable": {"thread_id": "task"}}
    )
    assert result["status"] == "finished"
    assert r.model.calls == 0
    assert len(store.find("execution", "task")) == 1


def test_specialist_repeated_reads_stop_before_budget(tmp_path, store):
    store.put("plan", {"id": "p"}, "task")
    r = runtime(
        tmp_path,
        store,
        [("execution_agent", {"goal": "查看执行计划"})]
        + [("read_record", {"kind": "plan", "record_id": "p"})] * 3
        + [("finish", {"answer": "受阻"})],
    )
    result = build_graph(r, InMemorySaver()).invoke(
        {"user_query": "执行计划"}, {"configurable": {"thread_id": "task"}}
    )
    assert result["status"] == "partial"
    assert r.model.calls == 5


def test_repeat_budget(tmp_path, store):
    r = runtime(tmp_path, store, [("paper_resolve", {"source": "1607.01759"})] * 4)
    result = build_graph(r, InMemorySaver()).invoke(
        {"user_query": "重复"}, {"configurable": {"thread_id": "task"}}
    )
    assert result["status"] == "partial"
    assert r.model.calls == 3


def test_paper_ingest_failure_stops_without_agent_sprawl(tmp_path, store):
    r = runtime(
        tmp_path,
        store,
        [
            ("paper_ingest", {"source": "https://arxiv.org/pdf/1607.01759"}),
            ("discovery_agent", {"goal": "不应执行"}),
        ],
    )

    def failed_ingest(source: str):
        """模拟论文基础设施失败。"""
        raise ValueError("Qdrant 不可用")

    r.paper.ingest = failed_ingest
    result = build_graph(r, InMemorySaver()).invoke(
        {"user_query": "论文用了哪些数据集？"},
        {"configurable": {"thread_id": "task"}},
    )
    assert result["status"] == "partial"
    assert result["fatal_error"] == "Qdrant 不可用"
    assert "论文处理失败" in result["final_answer"]
    assert r.model.calls == 1
