"""数据库连接、初始化与 PostgreSQL 到 SQLite 的启动期降级。"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from scitrace.persistence.tables import Base


@dataclass(frozen=True, slots=True)
class DatabaseRuntime:
    """应用实际选中的数据库及其连接工厂。"""

    engine: Engine
    session_factory: sessionmaker[Session]
    backend: str
    degraded: bool = False
    degradation_reason: str | None = None


def _prepare_sqlite_parent(database_url: str) -> None:
    """为文件型 SQLite 创建父目录；内存数据库无需处理。"""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    database_path = database_url.removeprefix(prefix)
    if database_path and database_path != ":memory:":
        Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _connect(database_url: str, *, echo: bool) -> Engine:
    """创建连接池并主动探活，确保降级只发生在应用启动阶段。"""
    _prepare_sqlite_parent(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, echo=echo, pool_pre_ping=True, connect_args=connect_args)
    if engine.url.get_backend_name() == "sqlite":
        # SQLite 默认不执行外键约束，必须显式开启才能与 PostgreSQL 保持一致。
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return engine


def create_database_runtime(
    primary_url: str,
    *,
    sqlite_fallback_url: str | None = None,
    allow_sqlite_fallback: bool = False,
    echo: bool = False,
) -> DatabaseRuntime:
    """连接主库，并在明确授权时于启动失败后降级到 SQLite。

    只允许 PostgreSQL 主库降级到 SQLite。运行期间发生写入失败时不会自动切换，
    否则可能在两个数据库中形成互相冲突的事实源。
    """
    try:
        engine = _connect(primary_url, echo=echo)
        backend = engine.url.get_backend_name()
        return DatabaseRuntime(engine, sessionmaker(engine, expire_on_commit=False), backend)
    except SQLAlchemyError as exc:
        if not allow_sqlite_fallback or sqlite_fallback_url is None:
            raise
        if not primary_url.startswith("postgresql"):
            raise ValueError("仅 PostgreSQL 主库支持 SQLite 降级") from exc
        if not sqlite_fallback_url.startswith("sqlite"):
            raise ValueError("降级数据库必须使用 SQLite URL") from exc

        engine = _connect(sqlite_fallback_url, echo=echo)
        return DatabaseRuntime(
            engine=engine,
            session_factory=sessionmaker(engine, expire_on_commit=False),
            backend="sqlite",
            degraded=True,
            degradation_reason=f"PostgreSQL 启动探活失败：{type(exc).__name__}: {exc}",
        )


def initialize_schema(runtime: DatabaseRuntime) -> None:
    """创建第一版实体表；后续结构升级应迁移到 Alembic。"""
    Base.metadata.create_all(runtime.engine)
