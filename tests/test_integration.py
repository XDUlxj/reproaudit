"""显式运行：SCITRACE_INTEGRATION=1 uv run pytest -m integration。
没有真实配置时跳过，不使用替身冒充服务验收。
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("SCITRACE_INTEGRATION") != "1", reason="未显式启用真实服务联调"),
]


def test_real_model_tools():
    from scitrace.cli import model_probe
    from scitrace.config import Settings

    settings = Settings()
    settings.require()
    model_probe(settings)


def test_real_postgres_and_checkpoint():
    import psycopg

    from scitrace.config import Settings

    with psycopg.connect(Settings().database_url.get_secret_value(), connect_timeout=5) as conn:
        assert (
            conn.execute("SELECT count(*) FROM scitrace.migrations WHERE version=1").fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT to_regclass('scitrace_checkpoints.checkpoints')").fetchone()[0]


def test_real_qdrant():
    from qdrant_client import QdrantClient

    from scitrace.config import Settings

    s = Settings()
    client = QdrantClient(
        url=s.qdrant_url, api_key=s.qdrant_api_key.get_secret_value() or None, timeout=5
    )
    assert client.get_collections() is not None


def test_real_tavily():
    import httpx

    from scitrace.config import Settings

    key = Settings().tavily_api_key.get_secret_value()
    response = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": "Bearer " + key},
        json={"query": "fastText official repository", "max_results": 2},
        timeout=20,
    )
    response.raise_for_status()
    assert response.json()["results"]


def test_real_docker():
    import subprocess

    from scitrace.config import Settings

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "1000:1000",
            "--read-only",
            "--cap-drop",
            "ALL",
            Settings().docker_image,
            "python",
            "-c",
            "import os; assert os.getuid()==1000; print('ok')",
        ],
        capture_output=True,
        timeout=60,
        check=True,
        text=True,
    )
    assert result.stdout.strip() == "ok"


def test_real_tmpfs_artifact_export(tmp_path):
    import subprocess
    from types import SimpleNamespace
    from uuid import uuid4

    from scitrace.config import Settings
    from scitrace.execution.runner import DockerRunner

    name = "scitrace-export-test-" + uuid4().hex[:12]
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--user",
            "1000:1000",
            "--cap-drop",
            "ALL",
            "--memory",
            "128m",
            "--cpus",
            "1",
            "--tmpfs",
            "/work:rw,size=16m,uid=1000,gid=1000",
            "--entrypoint",
            "/bin/sleep",
            Settings().docker_image,
            "60",
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                name,
                "python",
                "-c",
                "from pathlib import Path; Path('/work/model.bin').write_bytes(b'export-proof')",
            ],
            check=True,
            timeout=20,
        )
        output = tmp_path / "output"
        output.mkdir()
        DockerRunner(SimpleNamespace())._export(name, output, 16)
        assert (output / "model.bin").read_bytes() == b"export-proof"
    finally:
        subprocess.run(["docker", "stop", "--time", "1", name], capture_output=True, timeout=20)
