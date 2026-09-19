"""数据库选择和启动期降级测试。"""

from sqlalchemy.exc import OperationalError

from scitrace.persistence import create_database_runtime
from scitrace.persistence import database as database_module


def test_uses_sqlite_without_degradation_when_it_is_primary(tmp_path) -> None:
    runtime = create_database_runtime(f"sqlite+pysqlite:///{tmp_path / 'primary.db'}")
    try:
        assert runtime.backend == "sqlite"
        assert runtime.degraded is False
        assert runtime.degradation_reason is None
    finally:
        runtime.engine.dispose()


def test_postgresql_startup_failure_degrades_to_sqlite(tmp_path, monkeypatch) -> None:
    original_connect = database_module._connect

    def fake_connect(database_url: str, *, echo: bool):
        if database_url.startswith("postgresql"):
            raise OperationalError("SELECT 1", {}, RuntimeError("postgres unavailable"))
        return original_connect(database_url, echo=echo)

    monkeypatch.setattr(database_module, "_connect", fake_connect)
    runtime = create_database_runtime(
        "postgresql+psycopg://user:password@db/scitrace",
        sqlite_fallback_url=f"sqlite+pysqlite:///{tmp_path / 'fallback.db'}",
        allow_sqlite_fallback=True,
    )
    try:
        assert runtime.backend == "sqlite"
        assert runtime.degraded is True
        assert "OperationalError" in (runtime.degradation_reason or "")
    finally:
        runtime.engine.dispose()
