from types import SimpleNamespace

from scitrace.execution.runner import DockerRunner
from scitrace.models.core import ExecutionResult, ReproductionPlan, fingerprint


def test_completed_run_never_repeats(basic_runtime):
    r = basic_runtime
    r.policy.plan = lambda p: None
    plan = ReproductionPlan(claim_id="x")
    r.store.put("plan", plan)
    id = fingerprint([r.task_id, fingerprint(plan)])
    previous = ExecutionResult(
        id=id, plan_id=plan.id, plan_hash=fingerprint(plan), status="success"
    )
    r.store.put("execution", previous)
    runner = DockerRunner(r)
    runner._docker = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("不应重复执行 Docker"))
    assert runner.run(plan.id)["id"] == id


def test_unknown_run_not_replayed(basic_runtime):
    r = basic_runtime
    r.policy.plan = lambda p: None
    plan = ReproductionPlan(claim_id="x")
    r.store.put("plan", plan)
    id = fingerprint([r.task_id, fingerprint(plan)])
    r.store.put(
        "execution",
        ExecutionResult(
            id=id,
            plan_id=plan.id,
            plan_hash=fingerprint(plan),
            status="running",
            container_name="scitrace-test",
        ),
    )
    calls = []
    runner = DockerRunner(r)
    runner._docker = lambda args: calls.append(args) or SimpleNamespace(stdout='{"Running":false}')
    assert runner.run(plan.id)["status"] == "unknown"
    assert all(c[0] not in {"create", "start", "exec"} for c in calls)


def test_fasttext_metrics(basic_runtime):
    r = basic_runtime
    r.artifacts.write("log.txt", b"N 3000\nP@1 0.124\nR@1 0.0541\n")
    plan = ReproductionPlan(claim_id="x", metric_parser="fasttext")
    assert DockerRunner(r)._metrics(plan, r.artifacts.root, ["log.txt"])["P@1"] == 0.124


def execution_fixture(r, monkeypatch):
    from scitrace.models.core import CommandSpec

    r.policy.plan = lambda p: None
    r.policy.require = lambda *args, **kwargs: None
    r.downloader = SimpleNamespace(limit=500 * 1024**2)
    plan = ReproductionPlan(claim_id="x", commands=[CommandSpec(argv=["false"])])
    r.store.put("plan", plan)
    monkeypatch.setattr("scitrace.execution.runner.shutil.which", lambda name: "/bin/docker")
    runner = DockerRunner(r)
    calls = []
    runner._docker = lambda args, **kwargs: (
        calls.append(args) or SimpleNamespace(stdout="sha256:abc")
    )
    return runner, plan, calls


def test_docker_restrictions_and_nonzero_exit(basic_runtime, monkeypatch):
    runner, plan, calls = execution_fixture(basic_runtime, monkeypatch)
    process = SimpleNamespace(returncode=2, poll=lambda: 2)
    monkeypatch.setattr("scitrace.execution.runner.subprocess.Popen", lambda *a, **kw: process)
    result = runner.run(plan.id)
    assert result["status"] == "failed"
    assert result["commands_run"][0]["exit_code"] == 2
    create = next(args for args in calls if args[0] == "create")
    assert create[create.index("--network") + 1] == "none"
    assert create[create.index("--user") + 1] == "1000:1000"
    assert "--read-only" in create and "--cap-drop" in create
    assert any("/work:rw" in a and "size=1024m" in a for a in create)
    assert any("dst=/input,readonly" in a for a in create)
    assert create[-1] == "600"  # 主进程 TTL 限制，宿主崩溃也不会无限训练。


def test_timeout_logs_and_no_replay(basic_runtime, monkeypatch):
    runner, plan, calls = execution_fixture(basic_runtime, monkeypatch)
    process = SimpleNamespace(returncode=None, poll=lambda: None)

    def kill():
        process.returncode = -9

    process.kill = kill
    process.wait = lambda: -9
    monkeypatch.setattr("scitrace.execution.runner.subprocess.Popen", lambda *a, **kw: process)
    times = iter([0, 0, 0, 1000, 1000])
    monkeypatch.setattr("scitrace.execution.runner.time.monotonic", lambda: next(times))
    result = runner.run(plan.id)
    assert result["status"] == "failed"
    assert result["logs"]
    assert result["commands_run"][0]["status"] == "terminated"
    assert runner.run(plan.id)["id"] == result["id"]
