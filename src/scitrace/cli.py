"""CLI 只负责交互与恢复，不把科研编排固化成 pipeline。"""

import json
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import psycopg  # 连接 PostgreSQL 数据库的 "驱动库"
import typer
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from rich.console import Console

from scitrace.config import Settings
from scitrace.graph.builder import build_graph, execution_completion
from scitrace.models.core import ReproductionPlan, ResearchResource, fingerprint
from scitrace.models.task import Task
from scitrace.reporting.report import export_report
from scitrace.runtime import Runtime
from scitrace.storage import Artifacts, Store

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    help="SciTrace：科研主张追踪、复现计划与可审计执行",
)
console = Console()


@contextmanager
def services(settings, task):
    settings.require() # 校验 `.env` 是否配齐 `GLM_API_KEY`、`TAVILY_API_KEY`、`DATABASE_URL`
    store = Store(settings.database_url.get_secret_value()) # 连接数据库
    try:
        with psycopg.connect(
            settings.database_url.get_secret_value(), # **连接串（DSN）**，格式如 `postgresql://用户:密码@主机:端口/库名`。
            autocommit=True, # 每条 SQL 执行完立即生效，不需要手动 `commit()`
            prepare_threshold=0, # 关闭服务端语句预编译
            row_factory=dict_row, # 查询结果每行从默认元组变成字典
            connect_timeout=10, # 10 秒内连不上就报错
            options="-c search_path=scitrace_checkpoints,public", # **连接建立时给 PostgreSQL 下会话指令**：等效于先执行 `SET search_path = scitrace_checkpoints, public`
        ) as conn:
            saver = PostgresSaver(conn)
            runtime = Runtime(
                settings,
                store,
                task["id"],
                local_inputs=task.get("local_inputs", []),
                trusted_project_urls=task.get("trusted_project_urls", []),
                on_event=lambda e: console.print(
                    f"  {e['agent']} → {e['action']}: {e['status']}"
                    + (f" — {e['detail']}" if e.get("detail") else ""),
                    markup=False,
                ),
            )
            yield store, runtime, build_graph(runtime, saver)
    finally:
        store.close()


def model_probe(settings):
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=settings.glm_model,
        base_url=settings.glm_base_url,
        api_key=settings.glm_api_key.get_secret_value(),
        timeout=settings.model_timeout,
        max_retries=0,
        max_tokens=200,
    )
    schema = {
        "type": "function",
        "function": {
            "name": "probe",
            "description": "Return the supplied number.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        },
    }
    response = model.bind_tools([schema], tool_choice="required").invoke(
        [HumanMessage("Call probe with value 7.")]
    )
    if (
        len(response.tool_calls) != 1
        or response.tool_calls[0]["name"] != "probe"
        or response.tool_calls[0]["args"] != {"value": 7}
    ):
        raise ValueError("模型工具调用探针未通过，请检查 GLM_MODEL 和接口能力")


@app.command()
def init():
    """初始化专用 PostgreSQL schema 和 checkpoint 表（不修改其他应用表）。"""
    settings = Settings()
    if not settings.database_url.get_secret_value():
        raise typer.BadParameter("请配置 DATABASE_URL")
    store = Store(settings.database_url.get_secret_value())
    try:
        store.migrate()
        with psycopg.connect(
            settings.database_url.get_secret_value(),
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
            options="-c search_path=scitrace_checkpoints,public",
        ) as conn:
            PostgresSaver(conn).setup()
    finally:
        store.close()
    console.print("SciTrace 数据库初始化完成。")


@app.command()
def doctor(
    embedding: bool = False,
    skip_docker: bool = typer.Option(False, help="跳过 Docker 执行环境检查；仅验证追踪与规划能力。"),
    output: Path | None = None,
):
    """检查真实依赖。--skip-docker 适合暂不执行实验的本地追踪模式。"""
    settings = Settings()
    checks = []

    def check(name, fn):
        try:
            detail = fn()
            checks.append({"name": name, "status": "passed", "detail": str(detail or "OK")})
        except Exception as exc:
            checks.append(
                {"name": name, "status": "failed", "detail": settings.redact(str(exc))[:1000]}
            )

    check("configuration", settings.require)

    def postgres():
        if not settings.database_url.get_secret_value():
            raise ValueError("DATABASE_URL 未配置")
        with psycopg.connect(settings.database_url.get_secret_value(), connect_timeout=5) as conn:
            row = conn.execute(
                "SELECT to_regclass('scitrace.records'),to_regclass('scitrace_checkpoints.checkpoints')"
            ).fetchone()
            if not all(row):
                raise ValueError("服务可连接，但尚未 scitrace init")

    check("postgres", postgres)

    def qdrant():
        from qdrant_client import QdrantClient

        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key.get_secret_value() or None,
            timeout=5,
        ).get_collections()

    check("qdrant", qdrant)

    def glm():
        if not settings.glm_api_key.get_secret_value():
            raise ValueError("GLM_API_KEY 未配置")
        model_probe(settings)

    check("glm_tool_call", glm)

    def tavily():
        import httpx

        if not settings.tavily_api_key.get_secret_value():
            raise ValueError("TAVILY_API_KEY 未配置")
        response = httpx.post(
            "https://api.tavily.com/search",
            timeout=10,
            headers={"Authorization": "Bearer " + settings.tavily_api_key.get_secret_value()},
            json={"query": "fastText official", "max_results": 1},
        )
        response.raise_for_status()
        if "results" not in response.json():
            raise ValueError("Tavily 返回结构异常")

    check("tavily", tavily)

    def docker():
        if not shutil.which("docker"):
            raise ValueError("未找到 docker 命令，请安装并启动 Docker")
        subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=True)
        subprocess.run(
            ["docker", "image", "inspect", settings.docker_image],
            capture_output=True,
            timeout=10,
            check=True,
        )

    if skip_docker:
        checks.append(
            {
                "name": "docker_runner",
                "status": "skipped",
                "detail": "本地追踪模式：实验执行功能暂不可用",
            }
        )
    else:
        check("docker_runner", docker)

    def encoder():
        if not embedding:
            from huggingface_hub import try_to_load_from_cache

            path = try_to_load_from_cache(
                settings.embedding_model,
                "config.json",
                revision=settings.embedding_revision,
                cache_dir=str(settings.artifact_root / "models"),
            )
            if not isinstance(path, str):
                raise ValueError("本地模型未缓存，请运行 doctor --embedding；将首次下载模型")
            return "缓存存在；实际编码未测试（使用 --embedding 测试）"
        from scitrace.indexing.hybrid import HybridIndex

        index = HybridIndex(settings, Artifacts(settings.artifact_root))
        vector = index.encode(["scientific evidence"], query=True)[0]
        if len(vector) != 384:
            raise ValueError("embedding 维度必须为 384")
        return "本地 CPU 编码通过，384 维"

    check("embedding", encoder)
    for item in checks:
        console.print(f"{item['status']:6} {item['name']}: {item['detail']}", markup=False)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(checks, ensure_ascii=False, indent=2))
    if any(c["status"] == "failed" for c in checks):
        raise typer.Exit(1)


def refresh_task(settings, store, task):
    """进程可能在 checkpoint 保存后、任务摘要更新前崩溃；以 checkpoint 恢复待审批状态。"""
    with psycopg.connect(
        settings.database_url.get_secret_value(),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        connect_timeout=10,
        options="-c search_path=scitrace_checkpoints,public",
    ) as conn:
        checkpoint = PostgresSaver(conn).get_tuple({"configurable": {"thread_id": task["id"]}})
    if checkpoint:
        values = checkpoint.checkpoint.get("channel_values", {})
        for key in ("pending_approval", "final_answer", "observations", "status"):
            if key in values:
                if key == "status" and task.get("status") == "failed" and values[key] == "running":
                    continue
                task[key] = values[key]
    return task


def drive(settings, task, resume=False):
    with services(settings, task) as (store, runtime, graph):
        config = {
            "configurable": {"thread_id": task["id"]},
            "recursion_limit": settings.max_steps * 5 + 20,
        }
        with store.task_lock(task["id"]): # 任务锁，不允许同时跑两个项目，后续应改为 协程
            state = graph.get_state(config) # 给当前任务找checkpoint
            if resume: # 如果是旧任务
                if not state.values: # 当前chekpoint没有state执行现场的具体内容，则无法恢复
                    raise ValueError("任务没有可恢复 checkpoint")
                if not state.next: # 图已走完 + 数据库显示成功 → "假死"，补终态
                    # 图走完（checkpoint 已保存）→ 进程在 "把 finished 写进 task 记录" 之前崩了。
                    completed = execution_completion(runtime, state.values) # 查看数据库中是否有真实的记录
                    if completed and state.values.get("status") != "finished": # 查验仓库确实完成了，但checkpoint status还不是finished
                        # 仅协调已有成功账本的终态，不调用执行器、不改动实验历史。
                        graph.update_state(config, completed, as_node="supervisor") # as_node: 以supervisor的名义更新checkpoint
                        state = graph.get_state(config)
                    else:
                        console.print("任务已结束，无需恢复。") 
                        return
                pending = state.values.get("pending_approval") # 获取待审批的id
                if pending and store.get("approval", pending)["user_decision"] == "pending": # 如果存在审批任务且用户还未审批，则抛出异常
                    raise ValueError("存在待审批操作，请先 scitrace approve")
                incoming = Command(resume=True) if pending else None
            else: # 如果是新任务
                model_probe(settings) # 测试 LLM 能不能正常 tool calling
                incoming = {
                    "task_id": task["id"],
                    "user_query": task["query"],
                    "steps": 0,
                    "messages": [],
                    "observations": [],
                    "status": "running",
                    "requires_execution": task.get("requires_execution", False),
                } # 创建初始state
            failed = False
            try:
                graph.invoke(incoming, config)
            except Exception as exc:
                failed = True
                task["error"] = settings.redact(str(exc))[:2000] # 保存错误，但先脱敏
                task["status"] = "failed"
                store.put("task", task, task["id"]) # 立即写入数据库
                raise
            finally:
                snapshot = graph.get_state(config)
                task.update(
                    {
                        "status": "failed"
                        if failed
                        else snapshot.values.get("status", task.get("status", "failed")),
                        "final_answer": snapshot.values.get("final_answer"),
                        "pending_approval": snapshot.values.get("pending_approval"),
                        "observations": snapshot.values.get("observations", []),
                    }
                )
                store.put("task", task, task["id"])
                paths = export_report(store, runtime.artifacts, task["id"])
            console.print(f"任务状态：{task['status']}")
            if task.get("pending_approval"):
                console.print(f"待审批：{task['pending_approval']}；使用 status 查看具体操作。")
            if task.get("final_answer"):
                console.print(task["final_answer"], markup=False)
            console.print("报告：" + str(runtime.artifacts.path(paths[0])))


@app.command()
def run(
    query: Annotated[str, typer.Argument(help="自然语言目标")], # Python 的类型注解语法，把 "附加信息"（typer.Argument）挂到类型上，不改变类型本身
    paper: str | None = None,
    repository: str | None = None,
    plan: Path | None = None,
    require_execution: bool = False,
    trusted_project: list[str] | None = None,
):
    """创建新任务；本地文件只授权本命令显式提供的路径。"""
    settings = Settings()
    settings.require()
    task_id = str(uuid4())
    local_inputs = [] # 本地文件白名单
    for source in (paper, repository):
        if source and Path(source).exists():
            local_inputs.append(str(Path(source).resolve()))
    # Task 是任务摘要的唯一创建入口；后续字段演进先更新模型，再在这里显式赋值。
    task = Task(
        id=task_id,
        query=query,
        status="created",
        local_inputs=local_inputs,
        trusted_project_urls=trusted_project or [],
        requires_execution=require_execution or (
            bool(re.search(r"全链路|全流程|执行.*计划|复现实验|编译.*训练", query))
            and not bool(re.search(r"不执行|暂不|只.*分析|仅.*分析", query))
        ),
    )
    store = Store(settings.database_url.get_secret_value())
    try:
        if paper:
            source = str(Path(paper).resolve()) if Path(paper).exists() else paper
            task.query += "\n论文输入：" + source
        if repository:
            source = str(Path(repository).resolve()) if Path(repository).exists() else repository
            resource = ResearchResource(
                id=fingerprint([task_id, source]),
                url=source,
                reason="用户提供的仓库，尚未验证官方身份",
            )
            store.put("resource", resource, task_id)
            task.query += "\n已有仓库 resource_id：" + resource.id
        if plan:
            parsed = ReproductionPlan.model_validate_json(plan.read_text())
            # 导入外部计划生成任务内新 ID，不能覆盖先前已经审批的计划。
            parsed.id = str(uuid4())
            store.put("plan", parsed, task_id)
            task.query += "\n已有复现计划 plan_id：" + parsed.id
        # 数据库边界存 JSON；图和既有恢复逻辑继续读取字典，保证旧任务记录兼容。
        task_data = task.model_dump(mode="json")
        store.put("task", task_data, task_id)
    finally:
        store.close()
    console.print("任务 ID：" + task_id)
    drive(settings, task_data)


@app.command()
def status(task_id: str):
    """查看任务状态和待审批操作。"""
    settings = Settings()
    store = Store(settings.database_url.get_secret_value())
    try:
        task = refresh_task(settings, store, store.get("task", task_id))
        console.print_json(data=task)
        if task.get("pending_approval"):
            console.print_json(data=store.get("approval", task["pending_approval"]))
    finally:
        store.close()


@app.command()
def approve(task_id: str, approval_id: str, decision: str, response: str = ""):
    """记录 approved/rejected，随后用 resume 恢复；paper_selection 的 response 为候选序号。"""
    if decision not in {"approved", "rejected"}:
        raise typer.BadParameter("decision 必须为 approved 或 rejected")
    settings = Settings()
    store = Store(settings.database_url.get_secret_value())
    try:
        with store.task_lock(task_id):
            task = refresh_task(settings, store, store.get("task", task_id))
            record = store.get("approval", approval_id)
            if record["task_id"] != task_id or task.get("pending_approval") != approval_id:
                raise typer.BadParameter("审批不属于当前任务待审批操作")
            if record["user_decision"] != "pending":
                raise typer.BadParameter("审批已记录，不可改写历史决定")
            if record["approval_type"] == "paper_selection" and decision == "approved":
                candidates = record["requested_action"]["candidates"]
                if not response.isdigit() or not 1 <= int(response) <= len(candidates):
                    raise typer.BadParameter("--response 必须填写有效候选序号")
            record.update(user_decision=decision, response=response)
            store.put("approval", record, task_id)
    finally:
        store.close()
    console.print("审批已记录。运行 scitrace resume " + task_id)


@app.command()
def resume(task_id: str):
    """从持久 checkpoint 恢复同一任务。"""
    settings = Settings()
    store = Store(settings.database_url.get_secret_value())
    try:
        task = store.get("task", task_id)
    finally:
        store.close()
    drive(settings, task, resume=True)


@app.command()
def report(task_id: str):
    """重新导出 Markdown 与 JSON 报告。"""
    settings = Settings()
    store = Store(settings.database_url.get_secret_value())
    artifacts = Artifacts(settings.artifact_root)
    try:
        for ref in export_report(store, artifacts, task_id):
            console.print(str(artifacts.path(ref)))
    finally:
        store.close()


@app.command("prepare-fasttext")
def prepare_fasttext_command(output: Path = Path("artifacts/examples/fasttext-plan.json")):
    """下载官方小数据和代码，固定摘要，生成待审批验收计划；此命令不执行实验。"""
    from scitrace.examples import prepare_fasttext

    if output.exists():
        raise typer.BadParameter("输出已存在，请指定新的 --output，避免覆盖计划")
    from scitrace.tools.network import Downloader

    settings = Settings()
    plan = prepare_fasttext(
        output, Downloader(50 * 1024**2, trusted_fake_dns_hosts=settings.trusted_fake_dns_hosts)
    )
    console.print(f"已生成计划 {plan.id}：{output}")


def main():
    try:
        app()
    except Exception as exc:
        # 禁止 CLI traceback 展开本地变量或连接凭据。
        console.print("错误：" + Settings().redact(str(exc)), markup=False)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
