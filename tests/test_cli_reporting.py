import json

from typer.testing import CliRunner

from scitrace.cli import app
from scitrace.models.core import Evidence, ExecutionResult
from scitrace.reporting.report import export_report


def test_cli_help():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["doctor", "run", "status", "approve", "resume", "report"]:
        assert name in result.stdout


def test_report_has_source_and_execution_truth(basic_runtime):
    r = basic_runtime
    evidence = Evidence(kind="paper", source="paper.pdf", page=7, text="Claim evidence")
    r.store.put("evidence", evidence, r.task_id)
    r.store.put(
        "task",
        {"id": r.task_id, "query": "trace", "status": "finished", "final_answer": evidence.id},
        r.task_id,
    )
    result = ExecutionResult(
        plan_id="p", plan_hash="hash", status="failed", failure_reason="missing dataset"
    )
    r.store.put("execution", result, r.task_id)
    markdown, data = export_report(r.store, r.artifacts, r.task_id)
    assert "failed" in r.artifacts.path(markdown).read_text()
    report = json.loads(r.artifacts.path(data).read_text())
    assert report["evidence"][0]["page"] == 7
    assert report["execution"][0]["status"] == "failed"


def test_reject_invalid_approval_decision():
    result = CliRunner().invoke(app, ["approve", "task", "approval", "yes"])
    assert result.exit_code != 0
    assert "approved" in result.output


def test_report_keeps_paper_evidence_when_trace_is_missing(basic_runtime):
    r = basic_runtime
    evidence = Evidence(
        kind="paper", source="paper.pdf", page=3, text="Saved original", revision="cached-doc"
    )
    r.store.put("evidence", evidence, "previous-task")
    r.store.put("document", {"id": "cached-doc"}, r.task_id)
    r.store.put("task", {"id": r.task_id, "query": "experiment", "status": "partial"})
    md, data = export_report(r.store, r.artifacts, r.task_id)
    report = json.loads(r.artifacts.path(data).read_text())
    assert report["evidence"][0]["id"] == evidence.id
    assert "任务证据池" in r.artifacts.path(md).read_text()


def test_checkpoint_recovers_stale_pending_summary(monkeypatch, store):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from scitrace.cli import refresh_task
    from scitrace.config import Settings

    monkeypatch.setattr("scitrace.cli.psycopg.connect", lambda *a, **kw: nullcontext(object()))
    snapshot = SimpleNamespace(
        checkpoint={
            "channel_values": {"pending_approval": "approval-1", "status": "waiting_approval"}
        }
    )
    monkeypatch.setattr(
        "scitrace.cli.PostgresSaver",
        lambda conn: SimpleNamespace(get_tuple=lambda config: snapshot),
    )
    task = refresh_task(Settings(_env_file=None), store, {"id": "task", "status": "created"})
    assert task["pending_approval"] == "approval-1"
    assert task["status"] == "waiting_approval"
