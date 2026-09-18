import json
from datetime import UTC, datetime

KINDS = (
    "document",
    "repository",
    "resource_inspection",
    "resource",
    "discovery",
    "claim",
    "trace",
    "plan",
    "approval",
    "execution",
    "verification",
    "usage",
    "event",
)


def export_report(store, artifacts, task_id):
    task = store.get("task", task_id)
    report = {
        "schema_version": 1,
        "task": task,
        "exported_at": datetime.now(UTC).isoformat(),
        **{kind: store.find(kind, task_id) for kind in KINDS},
    }
    # 报告保留任务证据池，即使 Trace 未完成也不能丢失已经入库的论文原文。
    # 入库证据不等于支持某条 Claim，支持关系仍以 trace.links 为准。
    evidence_ids = {e["id"] for e in store.find("evidence", task_id)}
    for trace in report["trace"]:
        for claim in trace.get("claims", []):
            evidence_ids.update(claim.get("evidence_ids", []))
        for link in trace.get("links", []):
            evidence_ids.update(link.get("evidence_ids", []))
    for resource in report["resource"]:
        evidence_ids.update(resource.get("evidence_ids", []))
    # 简单问答没有 TraceResult，也收集回答中真实引用的 evidence ID。
    answer = task.get("final_answer") or ""
    document_ids = {d["id"] for d in report["document"]}
    for evidence in store.find("evidence"):
        # 跨任务复用缓存文档时，证据可能仍关联首次 ingestion 的任务。
        if evidence["id"] in answer or evidence.get("revision") in document_ids:
            evidence_ids.add(evidence["id"])
    report["evidence"] = [store.get("evidence", id) for id in sorted(evidence_ids)]
    json_ref = artifacts.json(f"tasks/{task_id}/report.json", report)
    lines = [
        "# SciTrace 科研证据报告",
        "",
        f"任务：`{task_id}`",
        "",
        f"状态：{task.get('status', 'unknown')}",
        "",
        "## 用户目标",
        "",
        task["query"],
        "",
        "## Agent 回答",
        "",
        answer or "任务尚未完成，以下为已保存结果。",
        "",
        "## 执行与验证事实",
        "",
    ]
    if not report["execution"]:
        lines += ["尚未实际执行实验；不能据此声称论文已复现。", ""]
    for execution in report["execution"]:
        lines += [
            f"- 执行 `{execution['id']}`：{execution['status']}，耗时 {execution.get('runtime_seconds', 0):.2f} 秒",
            f"- 指标：`{json.dumps(execution.get('metrics', {}), ensure_ascii=False)}`",
            f"- 失败原因：{execution.get('failure_reason') or '无'}",
            "",
        ]
    for verification in report["verification"]:
        lines += [
            f"- Verification：{verification['status']}；Provenance：{verification['provenance']}",
            f"- {verification['reason']}",
            f"- 可复现性评估：{verification['assessment']}",
            "",
        ]
    lines += [
        "## 原始证据",
        "",
        "以下为已保存的任务证据池；是否支持具体结论，以证据关联记录为准。",
        "",
    ]
    for evidence in report["evidence"]:
        location = (
            f"页 {evidence['page']}"
            if evidence.get("page")
            else f"行 {evidence.get('start_line')}–{evidence.get('end_line')}"
        )
        lines += [
            f"### `{evidence['id']}`",
            "",
            f"来源：{evidence['source']}；{location}；版本：{evidence.get('revision')}",
            "",
            "```text",
            evidence["text"].replace("```", "'''"),
            "```",
            "",
        ]
    for kind, heading in [
        ("resource", "资源来源"),
        ("repository", "仓库版本与索引"),
        ("resource_inspection", "实际下载核验"),
        ("trace", "证据关联与缺口"),
        ("plan", "复现计划"),
        ("approval", "审批记录"),
        ("execution", "命令、日志与产物"),
        ("usage", "模型用量"),
    ]:
        lines += [
            f"## {heading}",
            "",
            "```json",
            json.dumps(report[kind], ensure_ascii=False, indent=2).replace("```", "'''"),
            "```",
            "",
        ]
    md_ref = artifacts.write(f"tasks/{task_id}/report.md", "\n".join(lines).encode())
    return md_ref, json_ref
