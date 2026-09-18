import json
import math
import re
import shutil
import subprocess
import time

from scitrace.models.core import ExecutionResult, ReproductionPlan, fingerprint
from scitrace.tools.network import extract_archive, safe_path, sha256
from scitrace.validation.validator import effective_provenance, validate


class DockerRunner:
    def __init__(self, runtime):
        self.r = runtime

    def _docker(self, args, timeout=30):
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, check=True
        )

    def run(self, plan_id: str) -> dict:
        """Execute exactly the persisted, approved plan in a constrained Docker container; never run repo code on the host."""
        plan = ReproductionPlan.model_validate(self.r.store.get("plan", plan_id))
        self.r.policy.plan(plan)
        digest = fingerprint(plan)
        execution_id = fingerprint([self.r.task_id, digest])
        try:
            previous = ExecutionResult.model_validate(self.r.store.get("execution", execution_id))
            if previous.status == "running":
                # 进程崩溃后不猜测哪些命令已执行；检查容器并保留人工可恢复的事实。
                try:
                    state = self._docker(
                        ["inspect", "--format", "{{json .State}}", previous.container_name]
                    ).stdout.strip()
                    previous.failure_reason = "发现未完成执行记录，容器状态：" + state[:1000]
                    self._docker(["stop", "--time", "5", previous.container_name])
                except Exception:
                    previous.failure_reason = "执行中断且容器状态无法确认；禁止自动重跑"
                previous.status = "unknown"
                self.r.store.put("execution", previous, self.r.task_id)
            return previous.model_dump(mode="json")
        except KeyError:
            pass
        # 所有可预见的审批在执行账本创建前完成；否则恢复会误认为实验已开始。
        if plan.repository_id:
            repo = self.r.store.get("repository", plan.repository_id)
            self.r.policy.resource(self.r.store.get("resource", repo["resource_id"]))
            if repo["revision"] != plan.repository_revision:
                raise ValueError("计划 revision 与仓库快照不一致")
        for item in plan.resources:
            if item.resource_id:
                self.r.policy.resource(self.r.store.get("resource", item.resource_id))
        if not plan.commands:
            raise ValueError("计划没有可执行命令")
        self.r.downloader.limit = max(self.r.downloader.limit, plan.download_limit_mib * 1024**2)
        if not shutil.which("docker"):
            raise RuntimeError("未找到 Docker，请先安装并启动 Docker")
        image_id = self._docker(
            ["image", "inspect", "--format", "{{.Id}}", plan.image]
        ).stdout.strip()
        # 镜像 tag 可变，授权必须包含本次解析出的不可变 image ID。
        self.r.policy.require(
            "execution_image",
            {"plan_hash": digest, "image_id": image_id},
            "确认计划实际使用的本地容器镜像",
            "镜像内容变化需重新确认",
        )
        resource_statuses = []
        if plan.repository_id:
            repo_record = self.r.store.get("repository", plan.repository_id)
            resource_statuses.append(
                self.r.store.get("resource", repo_record["resource_id"])["resource_status"]
            )
        for item in plan.resources:
            if item.resource_id:
                resource_statuses.append(
                    self.r.store.get("resource", item.resource_id)["resource_status"]
                )
        name = "scitrace-" + execution_id[:24]
        result = ExecutionResult(
            id=execution_id,
            plan_id=plan.id,
            plan_hash=digest,
            status="running",
            provenance=effective_provenance(plan, resource_statuses),
            container_name=name,
            image_id=image_id,
        )
        self.r.store.put("execution", result, self.r.task_id)
        started = time.monotonic()
        workspace = self.r.artifacts.path(f"executions/{execution_id}/workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        output = self.r.artifacts.path(f"executions/{execution_id}/output")
        output.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            if plan.repository_id:
                repo = self.r.store.get("repository", plan.repository_id)
                if repo["revision"] != plan.repository_revision:
                    raise ValueError("计划 revision 与仓库快照不一致")
                shutil.copytree(
                    self.r.artifacts.path(repo["artifact"]), workspace / "repo", dirs_exist_ok=True
                )
            for resource in plan.resources:
                cached_download = self.r.artifacts.path("downloads/" + resource.sha256)
                if cached_download.is_file():
                    if cached_download.stat().st_size > plan.download_limit_mib * 1024**2:
                        raise ValueError("缓存资源超过计划下载预算")
                    data = cached_download.read_bytes()
                else:
                    data = self.r.downloader.get(resource.url)
                if sha256(data) != resource.sha256:
                    raise ValueError("资源 SHA256 不匹配：" + resource.url)
                if hasattr(self.r, "event"):
                    self.r.event("DockerRunner", "resource_ready", "completed", resource.url)
                target = safe_path(workspace, resource.destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                if resource.archive == "none":
                    if target.exists():
                        raise ValueError("拒绝覆盖已有资源")
                    target.write_bytes(data)
                else:
                    packed = workspace / (".download-" + resource.sha256)
                    packed.write_bytes(data)
                    extract_archive(
                        packed, target, resource.archive, plan.download_limit_mib * 1024**2
                    )
                    packed.unlink()
            # 宿主输入只读挂载，容器写入有容量上限的 tmpfs，防止填满宿主磁盘。
            for p in [workspace, *workspace.rglob("*")]:
                if p.is_symlink():
                    raise ValueError("实验目录禁止符号链接")
                p.chmod(0o755 if p.is_dir() else 0o644)
            self._docker(
                [
                    "create",
                    "--name",
                    name,
                    "--label",
                    "scitrace.execution=" + execution_id,
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "128",
                    "--cpus",
                    str(plan.cpus),
                    "--memory",
                    f"{plan.memory_mib}m",
                    "--memory-swap",
                    f"{plan.memory_mib}m",
                    "--user",
                    "1000:1000",
                    "--tmpfs",
                    "/tmp:rw,nosuid,size=128m",
                    "--tmpfs",
                    f"/work:rw,exec,nosuid,size={plan.disk_mib}m,uid=1000,gid=1000",
                    "--mount",
                    f"type=bind,src={workspace},dst=/input,readonly",
                    "--workdir",
                    "/work",
                    "--entrypoint",
                    "/bin/sleep",
                    image_id,
                    str(plan.timeout_seconds),
                ]
            )
            created = True
            self._docker(["start", name])
            self._docker(["exec", name, "cp", "-r", "/input/.", "/work/"], timeout=60)
            for i, command in enumerate(plan.commands):
                if hasattr(self.r, "event"):
                    self.r.event("DockerRunner", f"command_{i + 1}", "running", str(command.argv))
                remaining = plan.timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command.argv, plan.timeout_seconds)
                ref = f"executions/{execution_id}/command-{i}.log"
                path = self.r.artifacts.path(ref)
                entry = {**command.model_dump(), "exit_code": None, "status": "running"}
                result.commands_run.append(entry)
                result.logs.append(ref)
                self.r.store.put("execution", result, self.r.task_id)
                # 日志流式落盘，避免 stdout/stderr 进入 State 或撑爆内存。
                with path.open("wb") as log:
                    proc = subprocess.Popen(
                        [
                            "docker",
                            "exec",
                            "--workdir",
                            "/work/" + command.cwd,
                            name,
                            *command.argv,
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                    deadline = time.monotonic() + min(remaining, command.timeout_seconds)
                    try:
                        while proc.poll() is None:
                            if time.monotonic() >= deadline:
                                raise subprocess.TimeoutExpired(
                                    command.argv, command.timeout_seconds
                                )
                            if path.stat().st_size > 20 * 1024**2:
                                raise ValueError("单命令日志超过 20 MiB")
                            time.sleep(0.2)
                    finally:
                        if proc.poll() is None:
                            entry["status"] = "terminated"
                            try:
                                self._docker(["stop", "--time", "1", name])
                            finally:
                                proc.kill()
                                proc.wait()
                        else:
                            entry["status"] = "success" if proc.returncode == 0 else "failed"
                        entry["exit_code"] = proc.returncode
                        self.r.store.put("execution", result, self.r.task_id)
                if proc.returncode:
                    result.failure_type = classify_failure(
                        path.read_text(errors="replace")[-10000:]
                    )
                    raise RuntimeError(f"命令 {i + 1} 退出码 {proc.returncode}")
                if hasattr(self.r, "event"):
                    self.r.event("DockerRunner", f"command_{i + 1}", "completed")
            self._export(name, output, plan.disk_mib)
            result.metrics = self._metrics(plan, output, result.logs)
            result.status = "success"
        except Exception as exc:
            from scitrace.policy import NeedsApproval

            if isinstance(exc, NeedsApproval):
                # 资源审批必须在执行记录创建前完成；此分支仅作为防御，不允许被吞掉。
                result.status = "unknown"
                result.failure_reason = "执行准备阶段需要补充审批，请修订计划后重试"
            else:
                result.status = "failed"
                result.failure_type = result.failure_type or (
                    "hardware" if isinstance(exc, subprocess.TimeoutExpired) else "unknown"
                )
                result.failure_reason = self.r.settings.redact(str(exc))[:2000]
        finally:
            if created:
                try:
                    self._docker(["stop", "--time", "1", name])
                    self._docker(["rm", name])
                except Exception:
                    result.status = "unknown"
                    result.failure_reason = "容器清理失败，请通过任务 ID 检查容器状态"
            result.runtime_seconds = time.monotonic() - started
            result.repairs = [
                e["action"]
                for e in self.r.store.find("event", self.r.task_id)
                if e.get("status") == "retry"
            ]
            for p in output.rglob("*"):
                if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(output):
                    result.artifacts.append(str(p.relative_to(self.r.artifacts.root)))
            manifest = self.r.artifacts.json(
                f"executions/{execution_id}/artifacts.json", result.artifacts
            )
            result.artifacts = [manifest]
            self.r.store.put("execution", result, self.r.task_id)
        verification = validate(plan, result)
        self.r.store.put("verification", verification, self.r.task_id)
        return {
            **result.model_dump(mode="json"),
            "verification": verification.model_dump(mode="json"),
        }

    def _export(self, name, output, disk_mib):
        # Docker archive API 在本机未返回 tmpfs 内容；从容器进程读取挂载视图，
        # 流式落盘后使用同一安全解压器拒绝链接、越界和超大文件。
        archive = output.parent / "output.tar"
        error_log = output.parent / "export.log"
        with archive.open("wb") as stream, error_log.open("wb") as errors:
            process = subprocess.Popen(
                ["docker", "exec", name, "tar", "-C", "/work", "-cf", "-", "."],
                stdout=stream,
                stderr=errors,
            )
            deadline = time.monotonic() + 60
            try:
                while process.poll() is None:
                    if (
                        time.monotonic() > deadline
                        or archive.stat().st_size > (disk_mib + 32) * 1024**2
                    ):
                        raise ValueError("产物导出超时或超限")
                    time.sleep(0.1)
                if process.returncode:
                    raise RuntimeError(
                        "产物导出失败：" + error_log.read_text(errors="replace")[-1000:]
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        try:
            extract_archive(archive, output, "tar", disk_mib * 1024**2)
            if not any(p.is_file() for p in output.rglob("*")):
                raise ValueError("产物导出为空，不标记实验成功")
        finally:
            archive.unlink(missing_ok=True)

    def _metrics(self, plan, workspace, logs):
        if plan.metric_parser == "fasttext":
            metrics = {}
            for ref in logs:
                text = self.r.artifacts.path(ref).read_text(errors="replace")
                for key, value in re.findall(r"^(N|P@\d+|R@\d+)\s+([0-9.eE+-]+)\s*$", text, re.M):
                    metrics[key] = float(value)
        else:
            path = safe_path(workspace, plan.metric_file)
            if not path.exists():
                return {}
            if path.stat().st_size > 100000:
                raise ValueError("指标文件超限")
            metrics = json.loads(path.read_text())
        if not isinstance(metrics, dict) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in metrics.values()
        ):
            raise ValueError("指标必须是有限数值字典")
        return metrics


def classify_failure(text):
    text = text.lower()
    for words, kind in [
        (["modulenotfounderror", "no module named", "cannot find -l"], "dependency"),
        (["out of memory", "cuda", "killed"], "hardware"),
        (["checkpoint", "weights"], "checkpoint"),
        (["dataset", "data file"], "dataset"),
        (["syntaxerror", "traceback"], "code_bug"),
    ]:
        if any(word in text for word in words):
            return kind
    return "unknown"
