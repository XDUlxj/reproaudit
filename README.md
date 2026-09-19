# SciTrace V2

SciTrace V2 是面向科研复现、科学验证与可审计实验执行的多智能体应用。

当前阶段已落地项目骨架和领域模型。架构设计见 [`docs/`](docs/)。

## Persistence

PostgreSQL 是主存储，SQLite 可作为显式启用的启动期降级存储：

```python
from scitrace.persistence import create_database_runtime, initialize_schema

database = create_database_runtime(
    "postgresql+psycopg://scitrace:password@localhost/scitrace",
    sqlite_fallback_url="sqlite+pysqlite:///var/lib/scitrace/scitrace.db",
    allow_sqlite_fallback=True,
)
initialize_schema(database)
```

降级只在应用启动探活 PostgreSQL 失败时发生。运行期间事务失败不会自动切换数据库，
以免 PostgreSQL 与 SQLite 同时成为事实源。

## 本地校验

```bash
uv run pytest -q
uv run ruff check src tests
```
