from typing import Literal

from scitrace.models.core import ReproductionPlan, TraceResult, fingerprint


class TraceTools:
    def __init__(self, runtime):
        self.r = runtime

    def prepare_cooking_tutorial(
        self,
        repository_id: str | None = None,
        paper_evidence_id: str | None = None,
        code_evidence_id: str | None = None,
        tutorial_evidence_id: str | None = None,
    ) -> dict:
        """Prepare supported fastText Cooking plan. Prefer no arguments: selects the unique indexed fastText repository and retrieves real paper/code/tutorial evidence itself. Saves Claim/Trace/plan, no execution. Uses 12404/3000 split, defaults, 2 threads, P@1/R@1; tutorial only. Optional IDs must be exact tool references."""
        from scitrace.examples import DATA_URL
        from scitrace.models.core import Claim, CommandSpec, ResourceInput, TraceLink

        if repository_id is None:
            candidates = [
                item
                for item in self.r.store.find("repository", self.r.task_id)
                if self.r.store.get("resource", item["resource_id"])["url"].rstrip("/").lower()
                == "https://github.com/facebookresearch/fasttext"
            ]
            if len(candidates) != 1:
                raise ValueError("需要当前任务唯一的已索引 fastText 仓库，或显式指定 repository_id")
            repository_id = candidates[0]["id"]
        repo = self.r.store.get("repository", repository_id)
        if paper_evidence_id is None:
            documents = [
                d
                for d in self.r.store.find("document", self.r.task_id)
                if "1607.01759" in d["source"]
            ]
            if len(documents) != 1:
                raise ValueError("先由 Supervisor 入库 fastText 论文 1607.01759")
            hits = self.r.paper.search(documents[0]["index_id"], "fastText text classification", 3)
            paper_evidence_id = next((e["id"] for e in hits if e["kind"] == "paper"), None)
        if code_evidence_id is None:
            hits = self.r.repository.search(repository_id, "FastText::supervised", 5)
            code_evidence_id = next(
                (e["id"] for e in hits if e["kind"] == "code" and "src/fasttext.cc" in e["source"]),
                None,
            )
        if tutorial_evidence_id is None:
            hits = self.r.repository.search(repository_id, DATA_URL, 5)
            tutorial_evidence_id = next((e["id"] for e in hits if DATA_URL in e["text"]), None)
        if not all((paper_evidence_id, code_evidence_id, tutorial_evidence_id)):
            raise ValueError("检索未找到所需论文、代码或教程原文，不生成配方")
        resource = self.r.store.get("resource", repo["resource_id"])
        if resource["url"].rstrip("/").lower() != "https://github.com/facebookresearch/fasttext":
            raise ValueError("此受限验收配方仅支持已索引的 facebookresearch/fastText")
        paper = self.r.store.get("evidence", paper_evidence_id)
        code = self.r.store.get("evidence", code_evidence_id)
        tutorial = self.r.store.get("evidence", tutorial_evidence_id)
        if (
            paper["kind"] != "paper"
            or code["kind"] != "code"
            or code["revision"] != repo["revision"]
        ):
            raise ValueError("必须引用真实论文证据及当前仓库 revision 的代码证据")
        if "1607.01759" not in paper["source"] and "fasttext" not in paper["text"].lower():
            raise ValueError("论文证据必须来自 fastText 论文")
        if DATA_URL not in tutorial["text"]:
            raise ValueError("教程证据必须包含 Cooking 数据下载原始链接")
        measured = self.inspect_resource(DATA_URL)
        split = (
            "from pathlib import Path; rows=Path('data/cooking.stackexchange.txt').read_bytes().splitlines(keepends=True); "
            "assert len(rows)==15404; "
            "Path('cooking.train').write_bytes(b''.join(rows[:12404])); "
            "Path('cooking.valid').write_bytes(b''.join(rows[12404:])); "
            "print('train=12404 valid=3000')"
        )
        claim = Claim(
            id=fingerprint([repository_id, "cooking-tutorial"]),
            text="检验 fastText 官方 Cooking 分类教程能否在固定仓库版本上编译、训练和测试；不验证论文 benchmark。",
            evidence_ids=[paper_evidence_id, tutorial_evidence_id],
        )
        plan = ReproductionPlan(
            claim_id=claim.id,
            repository_id=repository_id,
            repository_revision=repo["revision"],
            image=self.r.settings.docker_image,
            target_scope="tutorial",
            provenance="assisted",
            resources=[
                ResourceInput(
                    url=DATA_URL, sha256=measured["sha256"], destination="data", archive="tar"
                )
            ],
            commands=[
                CommandSpec(argv=["make", "-j2"], cwd="repo"),
                CommandSpec(argv=["python", "-c", split]),
                CommandSpec(
                    argv=[
                        "./repo/fasttext",
                        "supervised",
                        "-input",
                        "cooking.train",
                        "-output",
                        "model_cooking",
                        "-thread",
                        "2",
                    ]
                ),
                CommandSpec(argv=["./repo/fasttext", "test", "model_cooking.bin", "cooking.valid"]),
            ],
            metric_parser="fasttext",
            changes=["线程数固定为 2；教程工程验收，不验证论文 benchmark"],
            assumptions=["使用教程默认科学参数；不预设 P@1/R@1 阈值，缺少比较规则返回 not_tested"],
        )
        result = self.save_plan(plan)
        trace = TraceResult(
            mode="code_assisted",
            claims=[claim],
            plan_id=plan.id,
            links=[
                TraceLink(
                    claim_id=claim.id,
                    evidence_ids=[paper_evidence_id, code_evidence_id, tutorial_evidence_id],
                    relationship="论文方法与仓库实现的候选关联；教程命令作为工程执行目标，非论文 benchmark 证据",
                    support="inferred",
                )
            ],
        )
        self.validate_result(trace.model_dump(mode="json"))
        return {"plan": result, "trace_id": trace.id, "claim_id": claim.id}

    def inspect_resource(self, url: str) -> dict:
        """Download an already identified public resource within budget and return its real SHA256 for a plan; does not execute it."""
        from scitrace.tools.network import sha256

        data = self.r.downloader.get(url)
        digest = sha256(data)
        ref = self.r.artifacts.write(f"downloads/{digest}", data)
        result = {
            "id": fingerprint([url, digest]),
            "schema_version": 1,
            "url": url,
            "sha256": digest,
            "bytes": len(data),
            "artifact": ref,
        }
        # 保存实际下载事实，不能仅凭模型生成的 64 位字符串认定摘要真实。
        self.r.store.put("resource_inspection", result, self.r.task_id)
        return result

    def save_plan(self, plan: ReproductionPlan) -> dict:
        """Validate and persist a reproduction plan. Commands are not executed. Unknown scientific settings must be listed as assumptions or blockers."""
        parsed = ReproductionPlan.model_validate(plan)
        if parsed.mode == "paper_only" and parsed.commands:
            raise ValueError("paper_only 计划不能包含实验命令；实际实验应使用 code_assisted")
        for command in parsed.commands:
            if command.argv[0] == "cd" or any(
                token in {"&&", "||", ";", ">", "|"} for token in command.argv
            ):
                raise ValueError("argv 不支持 shell 操作符或 cd；请使用 cwd 和独立结构化命令")
            if command.argv[0] in {"wget", "curl"}:
                raise ValueError(
                    "实验阶段默认断网；请将下载列入 resources，并使用 inspect_resource 核验"
                )
        if parsed.target_scope == "tutorial" and any(
            rule.scope != "tutorial" for rule in parsed.metric_rules
        ):
            raise ValueError("教程计划不能使用 paper_claim 比较规则")
        inspections = self.r.store.find("resource_inspection", self.r.task_id)
        for resource in parsed.resources:
            if not any(
                item["url"] == resource.url and item["sha256"] == resource.sha256
                for item in inspections
            ):
                raise ValueError(
                    f"资源摘要未经实际下载核验：{resource.url}；"
                    "请先调用 inspect_resource 并原样使用返回的 SHA256，不得编造"
                )
        for rule in parsed.metric_rules:
            if not rule.evidence_ids:
                raise ValueError("比较规则必须引用预先确定的证据")
            for id in rule.evidence_ids:
                self.r.store.get("evidence", id)
        if parsed.repository_id:
            repo = self.r.store.get("repository", parsed.repository_id)
            if repo["revision"] != parsed.repository_revision:
                raise ValueError("计划必须固定当前仓库 revision")
        try:
            old = self.r.store.get("plan", parsed.id)
            if old != parsed.model_dump(mode="json"):
                raise ValueError("计划不可原地覆盖；修订时使用新 ID 并递增 version")
        except KeyError:
            pass
        self.r.store.put("plan", parsed, self.r.task_id)
        return parsed.model_dump(mode="json")

    def read_record(
        self,
        kind: Literal[
            "document",
            "repository",
            "resource",
            "plan",
            "execution",
            "verification",
            "trace",
            "discovery",
        ],
        record_id: str,
    ) -> dict:
        """Read a record. Papers use kind=document; resource IDs are not repository IDs. Call index_repository(resource_id) first to obtain a repository record."""
        if kind not in {
            "document",
            "repository",
            "resource",
            "plan",
            "execution",
            "verification",
            "trace",
            "discovery",
        }:
            raise ValueError("不允许读取该记录类型")
        return self.r.store.get(kind, record_id)

    def validate_result(self, result: dict) -> dict:
        parsed = TraceResult.model_validate(result)
        claim_ids = {c.id for c in parsed.claims}
        for claim in parsed.claims:
            for id in claim.evidence_ids:
                self.r.store.get("evidence", id)
            try:
                old = self.r.store.get("claim", claim.id)
            except KeyError:
                pass
            else:
                if old["text"] != claim.text or old["evidence_ids"] != claim.evidence_ids:
                    raise ValueError("Claim 内容变化必须使用新 ID，不能覆盖历史证据关联")
        for link in parsed.links:
            if link.claim_id not in claim_ids:
                raise ValueError("证据关联引用不存在的 Claim")
            for id in link.evidence_ids:
                self.r.store.get("evidence", id)
        if parsed.plan_id:
            self.r.store.get("plan", parsed.plan_id)
        # 所有引用通过后再保存，避免校验失败留下半条证据链。
        for claim in parsed.claims:
            self.r.store.put("claim", claim, self.r.task_id)
        self.r.store.put("trace", parsed, self.r.task_id)
        return parsed.model_dump(mode="json")
