# SciTrace V2 --- E2E Contract Walk-through

> 目的：在正式编码前，把当前已经设计好的
> Entity、State、Agent-as-Tool、Routing、Persistence、Ingestion、Policy/HITL、Execution
> Runtime 串成一条端到端业务链，检查接口是否闭环。
>
> 当前状态：已检查到 `ExperimentRun terminal → Analysis verification`
> 之前。本文只记录已经确认的 E2E 结论；最后的科学验证与 Task
> 收敛仍需继续检查。

------------------------------------------------------------------------

## 1. 测试场景

使用一个典型科研复现请求贯穿系统：

``` text
“帮我复现论文 X 的 Table 3 实验。”
```

检查每一段时统一回答：

``` text
Input
→ Owner
→ Action
→ Output
→ Persistence / State
→ Next
```

这不是固定 Workflow。实际运行仍由 SciTraceAgent 根据当前 Task、State 和
Specialist Result 动态决定下一步。

------------------------------------------------------------------------

# 2. 用户请求 → Task

## Input

``` text
帮我复现论文 X 的 Table 3 实验。
```

## Owner

SciTrace Application / Task entry boundary。

## Action

创建正式 Task：

``` python
Task(
    query="帮我复现论文 X 的 Table 3 实验。",
    attachment_ids=[],
    status="created",
)
```

随后开始处理：

``` text
created → running
```

## Persistence

Task 进入 Postgres。

## Main State 初始化

``` python
SciTraceState(
    task_id=task.id,
    resources=[],
    experiment_spec=None,
    experiment_run=None,
    required_specialist=None,
    messages=[
        HumanMessage(
            content="帮我复现论文 X 的 Table 3 实验。"
        )
    ],
)
```

## 结论

``` text
✓ Contract 闭环
```

Task 是持久化业务请求；Main State 是当前工作快照。

------------------------------------------------------------------------

# 3. SciTraceAgent → DiscoveryAgent

## Input

Main Agent 当前知道：

``` text
用户目标：复现论文 X 的 Table 3
resources = []
experiment_spec = None
experiment_run = None
```

## Owner

SciTraceAgent。

## Action

Main 不需要先生成 `task_type=reproduction` 等固定分类字段。

它直接根据当前上下文判断：

> 当前没有足够科研资源，需要专业资源发现。

于是调用 DiscoveryAgent 这个 Agent-as-Tool。

## Child Context

不把整个 Main message history 原样传入
Specialist，而是传明确目标和结构化事实：

``` python
DiscoveryAgentState(
    task_id=task.id,
    resources=[],
    recovery_count=0,
    messages=[
        HumanMessage(
            content=(
                "Find and verify the scientific resources required "
                "to reproduce Table 3 of paper X, including the paper, "
                "official implementation repository, dataset, and "
                "required model/checkpoint when applicable."
            )
        )
    ],
)
```

## 结论

``` text
✓ Contract 闭环
```

Prompt 表达"这次为什么调用你"；State 表达"当前有哪些客观事实"。

------------------------------------------------------------------------

# 4. DiscoveryAgent → DiscoveryResult

## Owner

DiscoveryAgent。

## Action

可能执行：

``` text
Reason
 ↓
search_papers
 ↓
inspect_paper
 ↓
search_repositories
 ↓
inspect_repository
 ↓
search_datasets
 ↓
inspect_dataset
 ↓
...
```

## Output

``` python
DiscoveryResult(
    discovered_resources=[
        PaperResource(...),
        RepositoryResource(...),
        DatasetResource(...),
    ],
    summary=ResourceSummary(
        paper_count=1,
        repository_count=1,
        dataset_count=1,
        model_count=0,
    ),
)
```

DiscoveryAgent 的责任到：

> 找到并验证 ResearchResource。

它不直接管理 Postgres、Qdrant 或 embedding。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 5. DiscoveryResult → Persistence → Ingestion → Main State

这一段是 E2E 检查中发现并补清的第一个边界。

## 问题

之前分别定义了：

``` text
DiscoveryAgent
→ ResearchResource
```

以及：

``` text
AnalysisAgent
→ retrieve(...)
→ Qdrant
```

但如果 ResearchResource 只存在 Postgres，AnalysisAgent 不能直接进行
Dense/BM25/RRF 检索。

中间必须存在：

``` text
ResearchResource
→ Parse
→ Chunk
→ Dense/Sparse Encode
→ Qdrant
```

## 正式边界

DiscoveryAgent 本身不调用：

``` text
save_to_qdrant
chunk_resource
embed_resource
```

也不拥有 `index_resource` 之类 Agent Tool。

而是 Discovery Agent-as-Tool 的外层 Application/Wrapper 在 Specialist
成功返回后进行后处理：

``` text
DiscoveryAgent
      ↓
DiscoveryResult
      ↓
Application / Tool Wrapper
      ├── Persist ResearchResource → Postgres
      ├── 对支持 RAG 的资源执行 Ingestion
      └── Merge → Main State.resources
```

## Ingestion

对于 V1 支持全文检索的资源：

``` text
Paper
Repository
```

执行：

``` text
Resolve
 ↓
Parse
 ↓
Chunk
 ↓
Dense + Sparse Encode
 ↓
Qdrant
```

Dataset / Model V1 不要求默认全文索引。

## "自动"的含义

"自动进入向量库"不是 Qdrant 自动同步，也不是 DiscoveryAgent
自己决定调用一个 Qdrant Tool。

它表示：

> DiscoveryAgent 返回已经确认的新 ResearchResource 后，外层程序自动执行
> Persistence + Ingestion，不再让 LLM 做一次是否索引的决策。

## V1 时序

先采用同步边界：

``` text
DiscoveryResult
 ↓
Persist
 ↓
Ingestion
 ↓
Qdrant ready
 ↓
Merge Main State
 ↓
AnalysisAgent 可立即 retrieve
```

避免出现：

``` text
State 已有 paper_01
但 Qdrant 还没有 paper_01
→ retrieve() 暂时搜不到
```

## 结论

``` text
✓ Contract 闭环
```

这里没有新增 Agent、Entity 或 Agent-facing Tool，只补清了 Ingestion
的触发 owner。

------------------------------------------------------------------------

# 6. Main State → AnalysisAgent

此时：

``` python
SciTraceState(
    task_id="task_01",
    resources=[
        PaperResource(id="paper_01", ...),
        RepositoryResource(id="repo_01", ...),
        DatasetResource(id="dataset_01", ...),
    ],
    experiment_spec=None,
    experiment_run=None,
    required_specialist="analysis",
    messages=[...],
)
```

Paper / Repository 已经可以被 `retrieve()`。

## Routing

Discovery 本轮是为了补充 Analysis 所需资源，因此资源准备完成后：

``` python
required_specialist = "analysis"
```

## AnalysisAgent Input

``` python
AnalysisAgentState(
    task_id="task_01",
    resources=[...],
    experiment_spec=None,
    experiment_run=None,
    recovery_count=0,
    messages=[
        HumanMessage(
            content=(
                "Determine how to reproduce Table 3 of paper X. "
                "Construct an executable experiment specification "
                "and define the verification criteria."
            )
        )
    ],
)
```

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 7. AnalysisAgent → Retrieval / Inspection

AnalysisAgent 可以：

``` python
retrieve(
    query="Table 3 experiment setup datasets models metrics",
    resource_ids=["paper_01"],
)
```

然后：

``` python
retrieve(
    query="AID ResNet50 evaluation config",
    resource_ids=["repo_01"],
)
```

如果已知精确位置：

``` python
inspect_resource(
    resource_id="repo_01",
    locator=FileLocator(
        path="configs/aid/resnet50.yaml",
        start_line=1,
        end_line=80,
    ),
)
```

边界保持：

``` text
不知道位置 → retrieve
知道准确位置 → inspect_resource
```

AnalysisAgent 最终掌握：

``` text
目标实验
所需 Resource
执行命令
论文参考指标
验证标准
```

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 8. AnalysisAgent → ProposeSpec

AnalysisAgent 不直接创建正式 ExperimentSpec。

它返回：

``` python
ProposeSpec(
    action="propose_spec",
    proposal=ExperimentSpecProposal(
        spec=ExperimentSpecDraft(
            goal="Reproduce Table 3: ResNet50 on AID",
            resource_ids=[
                "repo_01",
                "dataset_01",
            ],
            commands=[
                "python test.py --config configs/aid/resnet50.yaml"
            ],
            verification_criteria=[
                MetricCriterion(
                    name="OA",
                    reference_value=94.2,
                    operator="approximately_equal",
                    tolerance=0.5,
                )
            ],
        ),
        rationale="...",
    ),
    summary="...",
)
```

其中 reference/tolerance 必须有明确依据，不能由 Agent 随意猜测。

## 责任边界

``` text
AnalysisAgent
→ 提出 ExperimentSpecDraft

外层控制层
→ Policy
→ HITL（如需要）
→ Materialize
→ Persist
```

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 9. ExperimentSpecDraft → ExperimentSpec

## 第一次 Spec

当前：

``` python
state["experiment_spec"] is None
```

根据已冻结 Spec Policy：

``` text
First ProposeSpec
 ↓
结构 / 业务校验
 ↓
默认 AUTO
 ↓
Materialize
```

Materialize：

``` python
ExperimentSpec(
    goal=draft.goal,
    resource_ids=draft.resource_ids,
    commands=draft.commands,
    verification_criteria=draft.verification_criteria,
    parent_spec_id=None,
)
```

继承 Record 后获得：

``` text
id
schema_version
created_at
```

## Persistence / State

顺序：

``` text
Materialize
 ↓
Persist ExperimentSpec → Postgres
 ↓
Update Main State.experiment_spec
 ↓
Inform Main LLM
```

## Routing

正式 Spec 存在后，不机械设置：

``` text
required_specialist = "execution"
```

因为用户可能只要求：

> 告诉我怎么复现。

对于当前示例：

> 帮我真实复现。

Main Agent 会根据用户目标、已有 Spec、尚无 Run，自主调用
ExecutionAgent。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 10. Analysis 缺资源支路

如果 Analysis 发现缺少 checkpoint：

``` python
NeedResources(
    action="need_resources",
    missing=[
        ResourceRequirement(
            kind="model",
            description="Official pretrained checkpoint required by Table 3."
        )
    ],
    summary="...",
)
```

则：

``` text
AnalysisAgent
 ↓
NeedResources
 ↓
required_specialist = discovery
 ↓
DiscoveryAgent
 ↓
Persist + Ingestion（如适用）
 ↓
resources 更新
 ↓
required_specialist = analysis
 ↓
AnalysisAgent
```

因此系统是动态循环：

``` text
Discovery
   ↓
Analysis
   ├── enough → ProposeSpec
   └── missing → Discovery → Analysis
```

不是固定 Pipeline。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 11. Spec Revision 支路

已有正式 Spec 后，AnalysisAgent 可以再次返回 ProposeSpec。

Policy 比较：

``` text
old ExperimentSpec
vs
new ExperimentSpecDraft
```

### Operational Revision

例如命令参数、工程性启动修正：

``` text
AUTO
```

新 Spec：

``` python
parent_spec_id = old_spec.id
```

### Semantic Revision

例如改变：

``` text
dataset
model
核心超参数
scientific goal
metric
verification criterion
```

则：

``` text
Semantic Revision
 ↓
HITL
 ↓
approve
 ↓
materialize new ExperimentSpec
```

旧 Spec 不原地修改。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 12. ExperimentSpec → ExecutionAgent

当前：

``` text
已有正式 ExperimentSpec
用户要求真实执行
当前没有有效 terminal ExperimentRun 满足目标
```

Main 调用 ExecutionAgent。

输入：

``` python
ExecutionAgentState(
    task_id="task_01",
    resources=[...],
    experiment_spec=spec_01,
    experiment_run=None,
    recovery_count=0,
    messages=[
        HumanMessage(
            content="Execute the current ExperimentSpec."
        )
    ],
)
```

ExecutionAgent 可以：

``` text
inspect_environment
inspect_workspace
prepare_resource
prepare_environment
```

直到具备真实执行条件。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 13. ExperimentRun 创建时机

ExperimentRun 不由 AnalysisAgent 创建，也不等实验结束后才创建。

正式时机：

> ExecutionAgent 已完成必要准备，Policy 允许第一次真实执行动作，即将启动
> command 时。

``` text
ExecutionAgent
 ↓
Preparation complete
 ↓
Execution Policy
 ↓ PASS
Create ExperimentRun
 ↓
status = running
 ↓
Persist
 ↓
Launch command
```

例如：

``` python
run = ExperimentRun(
    experiment_spec_id="spec_01",
    status="running",
)
```

这样即使进程启动后系统异常，也保留"run_01 曾真实发生"的业务事实。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 14. execute_command → Subprocess

Execution Runtime 启动真实子进程：

``` text
execute_command
 ↓
subprocess / Popen
 ↓
PID + create_time
```

更新：

``` python
run.execution_handle = LocalExecutionHandle(
    pid=...,
    create_time=...,
)
```

并创建实际开始执行的：

``` python
CommandRun(
    command="python test.py --config ...",
    status="running",
)
```

Runtime 负责：

``` text
process spawn
PID/create_time
stdout/stderr capture
timeout
process monitoring
exit code
ExperimentRun lifecycle plumbing
```

LLM 不负责这些机制。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 15. 长时间实验：Subprocess + Monitor

长实验不能让 LLM Tool Call 持续等待数小时，也不能让 Agent 周期性问：

``` text
跑完了吗？
跑完了吗？
跑完了吗？
```

已确定架构：

``` text
ExecutionAgent
 ↓
启动实验
 ↓
Execution Runtime
 ↓
OS Subprocess
 ↓
ExperimentRun.status = running
 ↓
Agent 不持续 reasoning

Monitor
 ↓
根据 PID + create_time 观察真实进程
 ↓
进程结束
 ↓
收集 exit_code / stdout / stderr
 ↓
更新 ExperimentRun terminal status
 ↓
触发 SciTrace 后续处理
```

状态：

``` text
running
→ succeeded
→ failed
→ interrupted
```

具体 Monitor 类名、调度方式、LangGraph 恢复 API
属于实现阶段，不再视为架构 Contract 缺口。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 16. 多 Command

ExperimentSpec 可以包含：

``` python
commands=[
    "python preprocess.py",
    "python train.py",
    "python evaluate.py",
]
```

它们属于同一个 ExperimentRun：

``` text
ExperimentRun run_01
├── CommandRun preprocess → succeeded
├── CommandRun train      → succeeded
└── CommandRun evaluate   → succeeded
```

CommandRun 只在命令真实开始时创建。

因此如果第二条命令失败：

``` text
command 1 → succeeded
command 2 → failed
command 3 → 未尝试，因此不存在 CommandRun
```

无需为了计划中的未执行命令新增 `pending` / `skipped`
状态；完整计划已经存在 `ExperimentSpec.commands`。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 17. Execution Success

当所有必要 command 技术执行成功：

``` text
ExperimentRun.status = succeeded
finished_at = ...
```

ExecutionAgent 通过 output collection / `inspect_output` 形成：

``` python
outputs=[
    MetricOutput(
        name="OA",
        value=94.08,
    ),
    ...
]
```

返回：

``` python
ExecutionSucceeded(
    experiment_run_id="run_01",
    outputs=[...],
)
```

Main State：

``` python
state["experiment_run"] = run_01
```

然后：

``` python
required_specialist = "analysis"
```

因为：

``` text
ExperimentRun.succeeded
≠
Scientific reproduction succeeded
```

技术执行成功后仍需要 AnalysisAgent 根据预定义 VerificationCriterion
做科学验证。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 18. Execution Failure 与 Retry

例如：

``` text
ModuleNotFoundError: timm
```

Runtime 将本次 Run 终结为：

``` python
ExperimentRun(
    status="failed",
    error="ModuleNotFoundError: No module named 'timm'",
    logs=[...],
)
```

ExecutionAgent 可以：

``` text
inspect_workspace / inspect_environment
 ↓
分析技术错误
 ↓
提出 evidence-supported operational recovery
 ↓
Policy / Budget
 ↓
prepare_environment / other allowed action
 ↓
retry
```

重试不是把：

``` text
run_01: failed → running
```

而是：

``` text
run_01 → failed
 ↓
technical recovery
 ↓
run_02 → running
```

历史 Run 保持不可伪造。

Scientific mismatch（程序成功运行但指标与论文差异较大）不属于
ExecutionAgent 的技术恢复判断，而交给 AnalysisAgent。

## 结论

``` text
✓ Contract 闭环
```

------------------------------------------------------------------------

# 19. 当前 E2E 总链路

截至目前已经检查：

``` text
User
 ↓
Task
 ↓
Persist Task
 ↓
SciTraceState
 ↓
SciTraceAgent
 ↓
DiscoveryAgent
 ↓
DiscoveryResult
 ↓
Persist ResearchResource
 ↓
Ingestion
 ↓
Qdrant
 ↓
Update Main State.resources
 ↓
AnalysisAgent
 ↓
retrieve / inspect_resource
 ↓
NeedResources ───────────────┐
 │                           │
 └→ Discovery → Analysis ────┘

或

ProposeSpec
 ↓
Spec Policy
 ↓
AUTO / HITL
 ↓
Materialize ExperimentSpec
 ↓
Persist
 ↓
Update Main State.experiment_spec
 ↓
SciTraceAgent
 ↓
ExecutionAgent
 ↓
prepare
 ↓
Execution Policy
 ↓
Create ExperimentRun.running
 ↓
Subprocess
 ↓
Monitor
 ↓
ExperimentRun terminal
 ↓
ObservedOutput / ExecutionResult
 ↓
Update Main State.experiment_run
 ↓
required_specialist = analysis
```

------------------------------------------------------------------------

# 20. E2E 检查中补清的关键点

## 20.1 Ingestion 触发边界

补清：

> DiscoveryAgent 返回已确认 ResearchResource 后，由外层 Application /
> Agent-as-Tool Wrapper 负责 Persistence + Ingestion；DiscoveryAgent
> 本身不直接操作 Qdrant。

这是 Tool wrapper 的后处理能力，不是 DiscoveryAgent 内部可选择的 Agent
Tool。

## 20.2 Draft → Formal Entity

补清：

> AnalysisAgent 只返回 ExperimentSpecDraft / ProposeSpec。Policy/HITL
> 通过后，由外层控制层 materialize 正式 ExperimentSpec，再持久化和更新
> Main State。

## 20.3 Long-running Experiment

确认已有设计：

> 长时间实验由 Subprocess + Monitor 承担；LLM
> 不轮询、不等待数小时。ExperimentRun 持久化真实生命周期，Monitor 在进程
> terminal 后触发 SciTrace 后续处理。

因此这一项不再视为待解决架构问题，具体恢复 API 属于实现阶段。

------------------------------------------------------------------------

# 21. 当前尚未完成的最后一段 E2E 检查

还需要继续检查：

``` text
ExperimentRun terminal
 ↓
AnalysisAgent
 ↓
inspect_run_evidence / verify
 ↓
GoalSatisfied
    或
Scientific Diagnosis
    或
NeedResources
    或
ProposeSpec
    或
UnableToResolve
 ↓
SciTraceAgent
 ↓
Task.finished / HITL / retry / failed
```

重点检查：

1.  AnalysisAgent 如何从 ExperimentRun 获得验证所需事实；
2.  `verify` 的输入输出如何与 VerificationCriterion / ObservedOutput
    对齐；
3.  `GoalSatisfied` 如何合法触发 Task.finished；
4.  Scientific mismatch 如何进入 diagnosis / Spec revision；
5.  无法解决时如何进入 HITL 或最终 Task.failed；
6.  最终 `Task.answer` 在哪个边界形成和持久化。

完成这一段后，E2E Contract Walk-through 才算正式结束，然后冻结 V2
Architecture 并进入编码阶段。
