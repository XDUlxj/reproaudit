"""离线核对真实任务报告、日志、论文定位与模型产物；不运行模型或实验。"""

import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader


def verify(task_id, root=Path("artifacts")):
    report = json.loads((root / "tasks" / task_id / "report.json").read_text())
    assert report["task"]["status"] == "finished", "任务终态尚未协调完成"
    for kind in ("document", "discovery", "repository", "trace", "plan", "approval", "verification"):
        assert report[kind], f"缺少阶段记录：{kind}"
    executions = report["execution"]
    assert len(executions) == 1, "验收任务必须只有一次实验执行"
    execution = executions[0]
    assert execution["status"] == "success"
    assert len(execution["commands_run"]) == 4
    assert all(c["exit_code"] == 0 for c in execution["commands_run"])
    assert execution["metrics"]["N"] == 3000
    assert all(0 <= execution["metrics"][k] <= 1 for k in ("P@1", "R@1"))
    plan = next(p for p in report["plan"] if p["id"] == execution["plan_id"])
    assert plan["target_scope"] == "tutorial"
    assert report["verification"][-1]["status"] == "not_tested"
    assert "train=12404 valid=3000" in (root / execution["logs"][1]).read_text()
    model_files = {}
    for name in ("model_cooking.bin", "model_cooking.vec"):
        path = root / "executions" / execution["id"] / "output" / name
        assert path.is_file() and path.stat().st_size > 0, f"缺少模型产物：{path}"
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        model_files[name] = {"bytes": path.stat().st_size, "sha256": digest, "path": str(path)}
    trace = next(t for t in report["trace"] if t.get("plan_id") == plan["id"])
    cited = {id for link in trace["links"] for id in link["evidence_ids"]}
    evidence = [e for e in report["evidence"] if e["id"] in cited]
    assert any(e["kind"] == "code" for e in evidence)
    papers = [e for e in evidence if e["kind"] == "paper"]
    assert papers
    for item in papers:
        document = next(d for d in report["document"] if d["id"] == item["revision"])
        page = PdfReader(root / document["artifact"]).pages[item["page"] - 1]
        assert item["text"] in page.extract_text().replace("\x00", " "), "论文引用无法回到原页"
    summary = {
        "task_id": task_id,
        "execution_id": execution["id"],
        "status": "passed",
        "metrics": execution["metrics"],
        "runtime_seconds": execution["runtime_seconds"],
        "repository_revision": plan["repository_revision"],
        "image_id": execution["image_id"],
        "models": model_files,
        "paper_quotes_verified": len(papers),
        "stages": {
            k: len(report[k])
            for k in (
                "document",
                "discovery",
                "repository",
                "trace",
                "plan",
                "approval",
                "execution",
                "verification",
            )
        },
        "scientific_verification": "not_tested: tutorial does not verify paper benchmark",
    }
    target = root / "acceptance" / "v0.1.1-cooking.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    verify(sys.argv[1])
