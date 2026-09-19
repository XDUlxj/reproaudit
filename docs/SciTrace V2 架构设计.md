
# 0. 总揽

## 0.1. 架构模块
```Plain text
SciTrace
│
├── Domain / Entity
│   │
│   ├── Task
│   │   ├── query
│   │   ├── attachment_ids
│   │   ├── status
│   │   └── answer
│   │
│   ├── ResearchResource
│   │   ├── PaperResource
│   │   ├── RepositoryResource
│   │   ├── DatasetResource
│   │   └── ModelResource
│   │
│   ├── ExperimentSpec
│   │   ├── goal
│   │   ├── resource_ids
│   │   ├── commands
│   │   ├── verification_criteria
│   │   │   ├── MetricCriterion
│   │   │   └── ArtifactCriterion
│   │   └── parent_spec_id
│   │
│   └── ExperimentRun
│       ├── experiment_spec_id
│       ├── status
│       ├── execution_handle
│       ├── command_runs
│       ├── outputs
│       │   ├── MetricOutput
│       │   └── ArtifactOutput
│       ├── logs
│       ├── error
│       └── finished_at
│
│
├── SciTraceAgent
│   │
│   ├── SciTraceState
│   │   ├── messages
│   │   ├── task_id
│   │   ├── resources
│   │   ├── experiment_spec
│   │   └── experiment_run
│   │
│   ├── Tools
│   │   ├── DiscoveryAgent-as-Tool
│   │   ├── AnalysisAgent-as-Tool
│   │   ├── ExecutionAgent-as-Tool
│   │   └── Basic Tools（还未想好）
│   │
│   ├── Policy(暂定)
│   │   ├── SpecChangePolicy
│   │   ├── ExecutionPolicy
│   │   └── CompletionPolicy
│   │
│   └── HITL
│
│
├── DiscoveryAgent
│   │
│   ├── DiscoveryAgentState
│   │   ├── messages
│   │   ├── task_id
│   │   ├── resources
│   │   └── recovery_count
│   │
│   ├── Tools(暂定)
│   │   ├── paper search
│   │   ├── repository search
│   │   ├── dataset/model search
│   │   ├── resource verification
│   │   └── ResourceStore
│   │
│   └── DiscoveryResult
│       ├── discovered_resources
│       └── summary
│
│
├── AnalysisAgent
│   │
│   ├── AnalysisAgentState
│   │   ├── messages
│   │   ├── task_id
│   │   ├── resources
│   │   ├── experiment_spec
│   │   ├── experiment_run
│   │   └── recovery_count
│   │
│   ├── Tools(暂定)
│   │   ├── RAG / retrieval
│   │   ├── paper analysis
│   │   ├── code search
│   │   ├── config parsing
│   │   └── verifier
│   │       ├── metric verifier
│   │       ├── artifact existence verifier
│   │       ├── structured artifact verifier
│   │       └── semantic artifact verifier
│   │
│   └── AnalysisResult
│       ├── NeedResources
│       ├── ProposeSpec
│       │   └── ExperimentSpecProposal
│       │       └── ExperimentSpecDraft
│       ├── KeepSpec
│       ├── GoalSatisfied
│       └── UnableToResolve
│
│
├── ExecutionAgent
│   │
│   ├── ExecutionAgentState
│   │   ├── messages
│   │   ├── task_id
│   │   ├── experiment_spec
│   │   ├── resources
│   │   └── recovery_count
│   │
│   ├── Tools / Services(暂定)
│   │   ├── environment preparation
│   │   ├── dependency checking
│   │   ├── process execution
│   │   ├── process monitoring
│   │   ├── output collection
│   │   └── ArtifactStore
│   │
│   └── ExecutionResult
│       ├── ExecutionSucceeded
│       ├── ExecutionFailed
│       └── ExecutionInterrupted
│
│
├── Agent-as-Tool Wrapper
│   │
│   ├── Discovery Wrapper
│   │   ├── Main State → DiscoveryAgentState
│   │   ├── invoke DiscoveryAgent
│   │   └── Command
│   │       ├── update resources
│   │       └── ToolMessage
│   │
│   ├── Analysis Wrapper
│   │   ├── Main State → AnalysisAgentState
│   │   ├── invoke AnalysisAgent
│   │   └── Command
│   │       ├── ToolMessage
│   │       └── confirmed Spec → update experiment_spec
│   │
│   └── Execution Wrapper
│       ├── Main State → ExecutionAgentState
│       ├── invoke ExecutionAgent
│       └── Command
│           ├── update experiment_run
│           └── ToolMessage
│
│
├── Persistence
│   ├── Postgres
│   │   ├── Task
│   │   ├── ResearchResource
│   │   ├── Task ↔ Resource relation
│   │   ├── ExperimentSpec
│   │   └── ExperimentRun
│   │
│   ├── Qdrant
│   │   └── semantic retrieval index
│   │
│   ├── BM25
│   │   └── lexical retrieval index
│   │
│   └── ArtifactStore
│       ├── logs
│       ├── checkpoints
│       ├── results
│       └── generated artifacts
│
└── Runtime
    ├── LangGraph Checkpointer
    ├── Middleware
    │   ├── tracing
    │   ├── token / cost tracking
    │   ├── retry
    │   └── tool protocol
    │
    └── Policies / HITL
```

## 0.2. 核心数据流
```Plain text
User
 │
 ▼
Task
 │
 ▼
SciTraceAgent
 │
 ├─────────────── DiscoveryAgent
 │                       │
 │                       ▼
 │                DiscoveryResult
 │                       │
 │               Command(update)
 │                       │
 │                       ▼
 │              Main.resources
 │
 ▼
AnalysisAgent
 │
 ├── NeedResources ───────────────→ Discovery
 │
 ├── ProposeSpec
 │       │
 │       ▼
 │   SpecChangePolicy
 │       │
 │    [HITL?]
 │       │
 │       ▼
 │   materialize
 │       │
 │       ▼
 │  Main.experiment_spec
 │
 ├── KeepSpec ────────────────────→ 保留当前 Spec
 │
 ├── GoalSatisfied ───────────────→ Task.finished
 │
 └── UnableToResolve ─────────────→ HITL / Task.failed
                                     
                 ExperimentSpec
                       │
                       ▼
                ExecutionAgent
                       │
                       ▼
                 ExperimentRun
                       │
                Command(update)
                       │
                       ▼
              Main.experiment_run
                       │
                       ▼
                 AnalysisAgent
                       │
              ┌────────┴────────┐
              ▼                 ▼
           Verifier           Diagnose
              │                 │
              ▼                 │
       GoalSatisfied            ├─ NeedResources
                                ├─ ProposeSpec
                                ├─ KeepSpec
                                └─ UnableToResolveq
```

# 1. SciTraceAgent（supervisor）

## 能力边界

```Plain text
SciTraceAgent
│
├── ① 全局理解与编排
│   ├── 理解用户意图
│   ├── 任务拆解
│   ├── Agent 分派
│   ├── Result 汇总
│   └── Replanning
│
├── ② 通用信息能力
│   ├── RAG 检索
│   ├── Entity 查询
│   ├── Evidence 查询
│   └── 基于已有信息总结/回答
│
└── ③ Agent-as-Tool
    ├── DiscoveryAgent
    ├── AnalysisAgent
    └── ExecutionAgent
```

# 2. DiscoveryAgent

>支持相互独立无数据依赖的任务串行

原则：

1. 有数据依赖 → 串行

2. 无数据依赖 → 允许并行

3. Subagent 不直接并发修改 Main State

4. 并行 Agent 各自返回 Result

5. fan-in 后由 Main / wrapper 统一 merge

6. V2 不实现通用任务 DAG Scheduler
```Plain text

                 DiscoveryAgent
                       │
             判断需要补充资源
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       Repo搜索      Dataset搜索    Model搜索
          │            │            │
          └────────────┼────────────┘
                       ▼
                  verify / persist
                       ↓
                DiscoveryResult
```

以下是一段discovery agent as tool 的示例



```python
@tool
def discovery_agent(
    request: str,
    runtime: ToolRuntime[SciTraceState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    result: DiscoveryResult = discovery_graph.invoke(
        {
            "task_id": runtime.state["task_id"],
            "resources": runtime.state["resources"],
            "recovery_count": 0,
            "messages": [
                HumanMessage(content=request)
            ],
        }
    )

    new_resources = [
        *runtime.state["resources"],
        *result.discovered_resources,
    ]

    return Command(
        update={
            # 更新主 SciTraceState
            "resources": new_resources,

            # 同时告诉主 Agent 本次发生了什么
            "messages": [
                ToolMessage(
                    content=result.summary.model_dump_json(),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )
```
# 最深的闭环调用链

```Plain text
用户科研目标
    ↓
Task
    ↓
SciTraceAgent
    ↓
DiscoveryAgent
    ↓
ResearchResource
    ↓
AnalysisAgent
    ↓
ExperimentSpec
    ├── commands
    └── verification_criteria
    ↓
ExecutionAgent
    ↓
ExperimentRun
    ├── command_runs
    ├── outputs
    ├── logs
    └── error
    ↓
AnalysisAgent
    ↓
Verifier Tools
    ↓
AnalysisResult
    ├── GoalSatisfied ─────────────→ Task.finished
    ├── NeedResources ─────────────→ DiscoveryAgent ──┐
    ├── ProposeSpec ───────────────→ 新 Spec ─────────┤
    ├── KeepSpec ──────────────────→ 可再次 Execution │
    └── UnableToResolve ───────────→ HITL / failed    │
                                                      │
                         ◀────────────────────────────┘
```