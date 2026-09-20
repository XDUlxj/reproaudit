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
from pathlib import Path

from qdrant_client import QdrantClient

from scitrace.persistence import LocalArtifactStore
from scitrace.retrieval import (
    FastEmbedHybridEncoder,
    IngestionService,
    LocalResourceResolver,
    QdrantHybridIndex,
    ResourceChunker,
    ResourceParser,
)

index = QdrantHybridIndex(
    QdrantClient(url="http://127.0.0.1:6333"),
    FastEmbedHybridEncoder(),
)
ingestion = IngestionService(
    LocalResourceResolver(),
    ResourceParser(LocalArtifactStore(Path("artifacts"))),
    ResourceChunker(),
    index,
)

ingestion.ensure_indexed(resource)
hits = index.retrieve("Table 3 experiment setup", [resource.id])
```

`retrieve` 强制要求 `resource_ids`，并在 Qdrant 内使用 Dense + BM25 双路召回与
RRF 融合。返回结果不暴露融合分数，只通过列表顺序表达排名。

Paper 使用 PyMuPDF4LLM 生成分页 Markdown（包括可提取的表格文本），检测到的图片进入
ArtifactStore；Repository 保留文件相对路径和真实行号。只有过长的天然单元才交给
LangChain splitter，SciTrace 适配层负责把字符位置还原为 locator。

## Agent Walking Skeleton

当前纵切使用真实 LangChain `create_agent`、LangGraph 状态图、tool calling 和 checkpoint，
三个 Specialist 的业务实现暂时是确定性 stub：

```python
from scitrace.agents import build_walking_skeleton_agent, initial_scitrace_state

agent = build_walking_skeleton_agent()
result = agent.invoke(
    initial_scitrace_state("task-001", "复现论文的主要实验结果"),
    config={"configurable": {"thread_id": "task-001"}},
)

assert result["goal_satisfied"] is True
```

它会自主完成 `Discovery → Analysis 提案 → Execution → Analysis 验证`。这里验证的是编排
闭环，不代表已经真实下载论文、执行代码或完成科学复现；后续迭代再逐个替换 Specialist stub。

## 本地校验

```bash
uv run pytest -q
uv run ruff check src tests
```
