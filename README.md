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

## Retrieval + Ingestion

第一版支持已 materialize 到本地的论文 PDF 和代码仓库：

```python
from qdrant_client import QdrantClient

from scitrace.retrieval import (
    DeterministicChunker,
    FastEmbedHybridEncoder,
    IngestionService,
    LocalResourceResolver,
    QdrantHybridIndex,
    ResourceParser,
)

index = QdrantHybridIndex(
    QdrantClient(url="http://127.0.0.1:6333"),
    FastEmbedHybridEncoder(),
)
ingestion = IngestionService(
    LocalResourceResolver(),
    ResourceParser(),
    DeterministicChunker(),
    index,
)

ingestion.ensure_indexed(resource)
hits = index.retrieve("Table 3 experiment setup", [resource.id])
```

`retrieve` 强制要求 `resource_ids`，并在 Qdrant 内使用 Dense + BM25 双路召回与
RRF 融合。返回结果不暴露融合分数，只通过列表顺序表达排名。

## 本地校验

```bash
uv run pytest -q
uv run ruff check src tests
```
