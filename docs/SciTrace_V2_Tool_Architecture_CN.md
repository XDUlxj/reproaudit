# SciTrace V2 --- Tool Architecture（V1 冻结稿）

> 本文整理 SciTrace V2 关于 Tool、RAG 与 Execution Runtime
> 边界的阶段性设计结论。
>
> 状态：V1 设计基线。目标：最小可用、可评测、可扩展，不提前过度设计。

## 1. Tool 设计总原则

SciTrace 从业务反推 Tool：

``` text
产品目标
→ 业务场景 / Use Case
→ 业务任务
→ Agent 职责
→ 完成职责所需的原子能力
→ 哪些能力需要 LLM 自主选择
→ Tool
→ 实现复杂或复用时再抽 Service
```

只有"LLM 需要根据当前 Observation
和目标，自主决定现在是否执行的外部动作"才优先成为 Agent-facing Tool。

不应作为 Tool 的典型能力：LLM 内部推理、Structured Output 构造、Entity
persistence、State
更新、Routing、Policy、HITL、checkpoint、进程监控、timeout、hash、ExperimentRun
lifecycle、Qdrant 内部 Dense/BM25/RRF、Resource normalization。

Tool API 是给 Agent 使用的业务动作接口；Service API
是给程序使用的实现接口。V1 不要求每个 Tool 后面都有 Service。只有被多个
Tool/非 Agent
代码复用、实现复杂需独立测试，或形成稳定外部集成边界时，再抽 Service。

共享实现不等于共享 Agent-facing Tool。例如 AnalysisAgent 的
`inspect_resource` 与 ExecutionAgent 的 `inspect_workspace` 可以共享底层
filesystem 实现，但语义、对象和权限不同，不应合并为万能 `read_file()`。

## 2. Agent 职责边界

### 2.1 SciTraceAgent

负责理解用户目标、评估当前上下文、判断缺少哪种专业能力、调用
Specialist、整合结果、判断目标完成并形成最终回答。

它主要调用：

``` text
DiscoveryAgent
AnalysisAgent
ExecutionAgent
```

Main Agent 不持有大量搜索、文件、shell 等 Specialist 低层 Tool。

### 2.2 DiscoveryAgent

核心职责：找到"正确的科研资源"，负责 Resource
Identity，而不是深入科研语义。

### 2.3 AnalysisAgent

核心职责：搞清楚科研资源意味着什么、实验应该怎么做、结果是否满足科研目标，以及科学差异来自哪里。

业务模式：

``` text
Scientific Understanding
Experiment Planning
Scientific Verification
Scientific Diagnosis
```

### 2.4 ExecutionAgent

核心职责：接收正式
ExperimentSpec，在受控环境中让实验真实发生，并报告实际发生了什么。它不判断科学复现是否成功。

## 3. DiscoveryAgent V1 Tool Set

``` text
search_papers
search_repositories
search_datasets
search_models

inspect_paper
inspect_repository
inspect_dataset
inspect_model
```

Search 用于外部 Candidate Discovery；Inspect 用于确认 Candidate
的身份、元数据和关联。

底层可以使用 OpenAlex、Crossref、arXiv、GitHub、Hugging Face、Web Search
等 provider，但不直接暴露
`search_arxiv`、`search_crossref`、`search_github` 等 provider-specific
Tool。

Discovery 中以下能力不是 Tool：搜索关键词生成、Candidate
信任判断、是否继续搜索、ResearchResource normalization、Resource
persistence、DiscoveryResult 构造。

## 4. AnalysisAgent V1 Tool Set

最终冻结为：

``` text
retrieve
inspect_resource
inspect_run_evidence
verify
```

### 4.1 retrieve

语义：在指定的、已接受并建立索引的 ResearchResource 中寻找与 query
相关的内容。

概念接口：

``` python
retrieve(
    query: str,
    resource_ids: list[str],
) -> list[RetrievalHit]
```

Agent 决定"搜什么、在哪些 Resource 中搜"；Retrieval Infrastructure
决定如何召回、融合和产生 Top-K。

因此不暴露
`dense_search`、`bm25_search`、`hybrid_search`、`rerank`、`search_paper`、`search_code`。

### 4.2 inspect_resource

语义：已经知道 ResearchResource 中的具体位置，直接读取该位置原始内容。

``` python
inspect_resource(
    resource_id: str,
    locator: ContentLocator,
) -> str
```

固定边界：

``` text
不知道答案在哪里 → retrieve
已经知道准确位置 → inspect_resource
```

`inspect_resource` 不经过 Qdrant。

### 4.3 inspect_run_evidence

用于读取 ExperimentRun 的实际运行证据，包括 stdout、stderr、execution
logs、CommandRun、produced artifacts 等。

ExperimentRun 不是 ResearchResource，因此 V1 不把 Run 强行塞入
`retrieve(resource_ids=...)`。精确参数待 Execution Artifact/Log contract
落地时冻结。

### 4.4 verify

按已定义的 VerificationCriterion 对 ObservedOutput
执行验证。AnalysisAgent 决定"验证什么、采用什么 criterion"，Verifier
负责确定性计算。

Metric：

``` text
approximately_equal:
abs(observed - reference) <= tolerance

greater_or_equal:
observed >= reference - tolerance

less_or_equal:
observed <= reference + tolerance
```

Artifact V1 优先支持
`existence`、`structured`。没有明确需求时，不提前构建万能 semantic LLM
Judge。

AnalysisAgent 中论文理解、Paper-Code
mapping、参数推导、ExperimentSpecDraft
构造、缺失资源判断、KeepSpec、Spec revision、Scientific
Diagnosis、GoalSatisfied 等属于 reasoning / structured output，而不是
Tool。

## 5. SciTrace V1 RAG 冻结方案

V1：

> resource scope filtering + Dense/BM25 双路召回 + RRF 融合 +
> 精确原文回源。

``` text
                  AnalysisAgent
                        │
          ┌─────────────┴─────────────┐
          │                           │
 retrieve(query, resource_ids)   inspect_resource
          │                           │
          ▼                           ▼
   resource_id filter            Raw Resource
          │
     ┌────┴────┐
     ▼         ▼
   Dense      BM25
     │         │
     └────┬────┘
          ▼
         RRF
          ▼
        Top-K
          ▼
   RetrievalHit[]
```

V1 明确不做：CrossEncoder/ColBERT reranker、GraphRAG、Knowledge
Graph、复杂 AST/Call Graph Retrieval、Query
decomposition、Multi-query、HyDE、Parent-child retrieval、Agentic
retrieval router、自动 Query Rewriting pipeline、多 Vector
DB、Elasticsearch、每种内容类型一个 Analysis search Tool。

独立 reranker 由 Eval 驱动：Recall@K 低时先解决召回；Recall@K 高但
MRR/nDCG 低时再考虑 reranker。

## 6. RetrievalHit 与 ContentLocator

``` python
class RetrievalHit(BaseModel):
    resource_id: str
    locator: ContentLocator
    content: str
```

不重复 `resource_kind`、`resource_name`。V1 不向 Agent 暴露 RRF
score，避免将排序融合分数误解为证据可信概率；list 顺序本身表达 ranking。

ContentLocator 指向 Resource 内部原始位置：

``` python
class PaperLocator(BaseModel):
    kind: Literal["paper"] = "paper"
    start_page: int
    end_page: int | None = None
    section: str | None = None


class FileLocator(BaseModel):
    kind: Literal["file"] = "file"
    path: str
    start_line: int | None = None
    end_line: int | None = None


ContentLocator = Annotated[
    PaperLocator | FileLocator,
    Field(discriminator="kind"),
]
```

三者边界：

``` text
ResourceLocation → Resource 在哪里
ContentLocator  → Resource 内部哪里
ResourceChunk   → 为检索如何切分
```

V1 不加入 LogLocator，因为 Run Evidence 不属于 ResearchResource RAG。

## 7. ResourceChunk 与 Qdrant

Chunk 是检索派生 DTO，不是 Domain Entity：

``` python
class ResourceChunk(BaseModel):
    resource_id: str
    content: str
    locator: ContentLocator
```

不继承 Record，也不存 embedding、sparse_vector、score、created_at
等索引基础设施字段。

Qdrant Point 逻辑结构：

``` text
Point
├── deterministic point_id
├── dense vector
├── sparse vector
└── payload
     ├── resource_id
     ├── content
     └── locator
```

V1 最重要的 payload filter/index 是 `resource_id`。不提前为 path/page
等建立大量 payload index。

Point ID 应可确定性生成，保证重复 ingestion 更易幂等；ResearchResource
自身负责版本身份，例如 RepositoryResource.revision 锁定 commit。

## 8. Chunking Strategy

总原则：优先天然结构边界；天然单元过长时才 deterministic length
split。V1 不做 LLM semantic chunking。

Paper：

``` text
PDF → Section → Paragraph → too long → length split
```

README/Markdown：

``` text
heading hierarchy → section → too long → length split
```

Source Code：

``` text
class / function / method / module block
→ too long → split
→ 无廉价 parser 时退化为 line/token split
```

这不等于构建复杂 AST Retrieval。

YAML/JSON/TOML：

``` text
small file → whole file
large file → top-level section/key
```

Script：

``` text
small → whole file
large → structural / length split
```

`MAX_CHUNK_TOKENS` 和 `CHUNK_OVERLAP`
为配置项，不写成领域规则。只有被迫长度切分时使用少量
overlap；天然结构单元间不机械 overlap。

## 9. Ingestion Pipeline

Ingestion 不是 Agent。

> DiscoveryAgent 负责发现并验证 ResearchResource；Ingestion
> Infrastructure 负责把已接受 Resource 转成可检索索引。

``` text
DiscoveryAgent
      ↓
verified resource
      ↓
ResearchResource
      ↓
persist
      ↓
ensure_indexed
      │
      ├── Resolve
      ├── Parse
      ├── Chunk
      ├── Encode
      └── Index
             ↓
           Qdrant
```

Resolve 固定 Resource 的可读取版本；Parse
只做确定性内容提取，不做科研理解；Chunk 输出 ResourceChunk；Encode 产生
dense+sparse representation；Index 写入 Qdrant。

V1 ingestion 尽量幂等。重建可采用：

``` text
delete points where resource_id = X
→ Parse
→ Chunk
→ Encode
→ Index
```

不提前实现复杂 incremental chunk diff。

ResearchResource 暂不增加
`indexed`、`index_status`、`chunk_count`、`embedding_model`、`indexed_at`
等基础设施状态字段。

## 10. Execution：Agent 与 Runtime 边界

固定原则：

> ExecutionAgent 负责决策；Execution Runtime 负责机制。

``` text
ExecutionAgent
“下一步应该做什么？”
        ↓
Execution Tools
“允许 Agent 发起哪些受控动作？”
        ↓
Execution Runtime
“怎样可靠、安全地执行？”
        ↓
OS / filesystem / process / network
```

ExecutionAgent 负责选择下一步动作、分析技术错误、选择 evidence-supported
recovery。

Runtime 负责 clone/checkout 的机制、filesystem、process
spawn、PID/create_time、stdout/stderr
capture、monitoring、timeout、artifact hash、ExperimentRun lifecycle
plumbing。

Policy 负责动作是否合法、敏感操作是否 HITL、retry/budget 是否允许继续。

## 11. ExecutionAgent V1 Tool Set

``` text
inspect_environment
inspect_workspace
prepare_resource
prepare_environment
execute_command
inspect_output
```

### inspect_environment

检查 Python、CUDA、GPU、disk、runtime availability 等 Host Environment。

### inspect_workspace

检查当前受控 workspace，例如 repo
是否存在、revision、文件/目录、依赖描述文件、配置等。

Host Environment 与 Task Workspace 是不同对象，不合成万能
`inspect_execution_context`。

### prepare_resource

将已验证 ResearchResource materialize 到 workspace：

``` text
RepositoryResource → clone / checkout
DatasetResource    → download / link / materialize
ModelResource      → download / materialize
```

不负责发现资源或判断官方性。

### prepare_environment

根据已掌握依赖信息准备隔离环境，底层可使用
uv/pip/venv/conda，但不直接暴露这些低层 Tool。

Runtime 安装失败后不能自行"猜版本"；失败 Observation 返回
ExecutionAgent，由 Agent 基于证据选择恢复动作，再经过 Policy。

### execute_command

执行正式 ExperimentSpec 中的命令。Runtime 接管
spawn、logs、PID、monitor、timeout、ExperimentRun update。

长任务不通过 LLM 周期性调用 `poll_process` / `wait_process` /
`check_finished` 监控。

### inspect_output

从实际 stdout、日志和结果文件中定位并提取科研输出，形成
`ObservedOutput[]`。

VerificationCriterion 已经提供"必须获取什么"的核心信息，因此 V1
不重新引入 OutputRequirement。

明显有科研价值的 result/prediction/checkpoint/figure
可以持久化；cache、临时文件等不应无差别进入 outputs。

## 12. ExecutionAgent 不直接拥有的低层 Tool

V1 不直接暴露：

``` text
shell
bash
python_exec
arbitrary_file_write
arbitrary_download
pip_install
git_clone
kill_process
sudo
```

这些若需要，由受控 Runtime 在高层 Tool 内实现。

## 13. 三个 Specialist 的最终 Tool 视图

``` text
SciTraceAgent
│
├── DiscoveryAgent
│   ├── search_papers
│   ├── search_repositories
│   ├── search_datasets
│   ├── search_models
│   ├── inspect_paper
│   ├── inspect_repository
│   ├── inspect_dataset
│   └── inspect_model
│
├── AnalysisAgent
│   ├── retrieve
│   ├── inspect_resource
│   ├── inspect_run_evidence
│   └── verify
│
└── ExecutionAgent
    ├── inspect_environment
    ├── inspect_workspace
    ├── prepare_resource
    ├── prepare_environment
    ├── execute_command
    └── inspect_output
```

这不是固定 Pipeline。Specialist 仍由 SciTraceAgent 根据 Task 和 State
动态调用。

横切能力：

``` text
Policy
HITL
Routing
Persistence
Checkpoint
Middleware
Execution Runtime
Retrieval Infrastructure
```

它们不是新的 Agent。

## 14. V1 冻结结论

1.  Tool 从业务职责反推，不从 API/Service 反推。
2.  一个业务任务不等于一个 Tool。
3.  Tool 是 Agent 可自主选择的有边界外部动作。
4.  Service 是否存在由复用和实现复杂度决定，不强制一 Tool 一 Service。
5.  Discovery 负责 Resource Identity。
6.  Analysis 负责 Resource Semantics、Experiment Planning、Scientific
    Verification、Scientific Diagnosis。
7.  Execution 负责真实执行与实际事实收集。
8.  Main Agent 不持有大量 Specialist 低层 Tool。
9.  Analysis RAG 使用 `retrieve + inspect_resource`。
10. V1 Retrieval = resource filter + Dense/BM25 + RRF。
11. V1 不上独立 reranker；是否增加由 Retrieval Eval 决定。
12. Run Evidence 不强行并入 ResearchResource RAG。
13. Chunk 是检索派生 DTO，不是 Entity。
14. Ingestion 是确定性基础设施，不是 Agent。
15. ExecutionAgent 负责决策，Execution Runtime 负责机制。
16. 进程监控、timeout、ExperimentRun lifecycle 不作为 LLM Tool。
17. VerificationCriterion 已表达必须收集的科研结果，不重新引入
    OutputRequirement。
18. Policy、HITL、Routing、Persistence 与 Tool 保持正交。

## 15. 下一步

Tool 层完成后，不继续局部扩展 Tool。下一步进行完整端到端 Contract
Walk-through：

``` text
Task
↓
SciTraceAgent
↓
DiscoveryAgent
↓
ResearchResource
↓
Ingestion
↓
AnalysisAgent
↓
ExperimentSpec
↓
ExecutionAgent
↓
ExperimentRun
↓
AnalysisAgent Verification
↓
GoalSatisfied
↓
Task.finished
```

逐步检查：

``` text
输入从哪里来
→ 谁负责
→ 调什么 Agent / Tool
→ 返回什么 DTO / Entity
→ 谁持久化
→ Main State 更新什么
→ 下一步为什么能够继续
```

确认整个业务闭环不存在 Contract 断点后，再进入具体代码实现。
