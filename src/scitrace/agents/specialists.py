from pydantic import BaseModel, Field

from scitrace.agents.loop import AgentLoop, tool_for
from scitrace.models.core import DiscoveryResult, TraceResult


class ExecutionSummary(BaseModel):
    execution_id: str | None = None
    status: str
    blockers: list[str] = Field(default_factory=list)


def make_specialists(r):
    def prepare_cooking_tutorial() -> dict:
        """Prepare the supported fastText Cooking plan with NO arguments. Reads the current task's unique indexed repository and ingested paper, retrieves real evidence and measures data SHA256. Saves Trace and plan for approval. Call after index_repository; do not provide IDs."""
        return r.trace.prepare_cooking_tutorial()

    paper = [
        tool_for(r.paper.search, "paper_hybrid_search"),
        tool_for(r.paper.evidence, "read_evidence"),
    ]
    read = tool_for(r.trace.read_record, "read_record")

    def discovery_result(data):
        parsed = DiscoveryResult.model_validate(data) # 检查 DiscoveryAgent 输出的格式，但还未证明resource真的存在
#       data = {
#           "resource_ids": ["res_001"],
#           "evidence_ids": ["ev_001"],
#           "official_repository": "res_001",
#           "missing_resources": []
#       }
        resources = r.store.find("resource", r.task_id) # 从库中找到真正的资源

        def resolve_resources(reference):
            """验证 LLM 给的 Resource 和 Evidence 是否真实存在"""
            matches = [item for item in resources if item["id"] == reference] # 先看id ❗️为什么看id？
            if not matches: # 但是 LLM 有时候可能不按要求，直接返回 url，所以允许从url反向找到 resource id
                # URL 是资源身份入口；重复注册时保留所有匹配记录，不任意
                # 选择一个记录或扩大其官方身份/审批权限。
                matches = [item for item in resources if item["url"] == reference]
            if not matches:
                known = [{"id": item["id"], "url": item["url"]} for item in resources[-20:]]
                raise ValueError(f"无效的任务资源引用：{reference!r}；合法资源：{known}")
            return matches

        parsed.resource_ids = list(
            dict.fromkeys(
                item["id"] for ref in parsed.resource_ids for item in resolve_resources(ref)
            )
        )
        for id in parsed.evidence_ids: # 验证 LLM 给出的 evidence 也是真实的
            try:
                r.store.get("evidence", id)
            except KeyError:
                known = list(
                    dict.fromkeys(e for item in resources for e in item.get("evidence_ids", []))
                )[-30:]
                raise ValueError(
                    f"不存在的 evidence ID：{id!r}；已注册资源引用的真实 evidence ID：{known}"
                ) from None
        if parsed.official_repository: # 验证官方仓库
            matches = resolve_resources(parsed.official_repository)
            official = [item for item in matches if item["resource_status"] == "official"] # 查验数据库
            if not official:
                # 以已经核验的持久记录为准，不能采用模型的“官方”自述。
                parsed.official_repository = None
                parsed.resource_ids = list(
                    dict.fromkeys([*parsed.resource_ids, *(item["id"] for item in matches)])
                )
                parsed.missing_resources = list(
                    dict.fromkeys([*parsed.missing_resources, "仓库官方身份尚未核实，使用仍需审批"])
                )
            elif len(official) != 1:
                raise ValueError(
                    "official_repository 必须指定唯一的已验证官方资源 ID；"
                    "未验证时设为 null，保留 resource_ids 和缺口，不要继续重复搜索"
                )
            else:
                parsed.official_repository = official[0]["id"]
        r.store.put("discovery", parsed, r.task_id)
        return parsed.model_dump(mode="json")

    def execution_result(data):
        if data.get("execution_id"):
            # 以执行器持久化事实覆盖 LLM 的执行结论。
            return r.store.get("execution", data["execution_id"])
        return {"status": "not_tested", "blockers": data["blockers"]}

    return {
        "discovery_agent": AgentLoop(
            r,
            "DiscoveryAgent",
            "只发现和验证科研资源，不做 Claim 推理，不执行实验。资源必须 register 后返回 ID。",
            [
                tool_for(r.discovery.search, "search_resources"),
                tool_for(r.discovery.fetch, "fetch_page"),
                tool_for(r.discovery.register, "register_resource"),
                read,
            ],
            DiscoveryResult,
            discovery_result,
        ),
        "trace_agent": AgentLoop(
            r,
            "TraceAgent",
            "针对目标 Claim 检索论文和仓库，建立证据链并在信息足够时 save_plan。"
            "对于 fastText Cooking 教程优先使用 prepare_cooking_tutorial 生成已支持的受限配方；需要论文、代码、含数据链接的教程 evidence ID。"
            "索引仓库后用 repository_hybrid_search 查找 README、教程、配置和命令。"
            "下载在资源准备阶段通过 inspect_resource 核验，实验阶段断网。"
            "教程实验 target_scope=tutorial，metric_parser 取实际输出格式；"
            "没有可信阈值可以 metric_rules=[]，不能编造指标。"
            "blockers 仅记真实缺口，不预设编译失败或内存不足；"
            "shell 的 cd/&& 不是独立可执行 argv，请使用 cwd 和结构化命令。"
            "缺少代码可 paper_only，但不能在 paper_only 计划内执行命令。禁止搜索外部资源或执行实验。",
            [
                *paper,
                tool_for(r.repository.index, "index_repository"),
                tool_for(r.repository.search, "repository_hybrid_search"),
                read,
                tool_for(r.trace.save_plan, "save_plan"),
                tool_for(r.trace.inspect_resource, "inspect_resource"),
                tool_for(prepare_cooking_tutorial, "prepare_cooking_tutorial"),
            ],
            TraceResult,
            r.trace.validate_result,
        ),
        "execution_agent": AgentLoop(
            r,
            "ExecutionAgent",
            "只能执行已经持久化的计划。检查计划、调用 execute_plan 并报告事实；不得自行改变实验目标、依赖或源码，不得声称 Claim 被验证。",
            [read, tool_for(r.runner.run, "execute_plan")],
            ExecutionSummary,
            execution_result,
        ),
    }
