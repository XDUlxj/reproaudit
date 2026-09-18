# SciTrace V1 架构设计（Canonical Freeze）

> 状态：V1 架构冻结\
> 冻结日期：2026-09-14\
> 核心框架：LangGraph + LangChain\
> 架构模式：1 个 Supervisor Agent Loop + Basic Paper Tools + 3 个
> Agent-as-Tool\
> V1 不包含 Skills，不包含 PaperAnalysisAgent，不包含 Paper Analysis
> Subgraph。

------------------------------------------------------------------------

## 1. 项目定位

SciTrace 是一个面向科研论文的 **Scientific Claim Traceability &
Reproducibility Agent**。

它不是普通论文问答助手，也不是简单的"自动运行 GitHub 仓库"工具。SciTrace
的核心价值是围绕用户关心的科学主张建立可追踪的证据链，并在条件允许时生成和执行复现方案。

核心证据链：

``` text
Scientific Claim
        ↓
Paper Evidence
        ↓
Method / Experimental Setting
        ↓
Code / Config / Dataset / Checkpoint
        ↓
Experiment
        ↓
Execution
        ↓
Result
        ↓
Verification
        ↓
Reproducibility Assessment
```

核心问题：

> 一个 Scientific Claim
> 是由什么论文证据、代码、配置和实验支撑的？这些条件是否足够明确？在当前资源与环境下能否重新验证？

------------------------------------------------------------------------

## 2. V1 设计原则

V1 遵循以下原则：

1.  用户可以从自然语言、论文标题、DOI、arXiv ID、URL、PDF、Repository
    等任意合理入口开始。
2.  不要求固定先上传 PDF。
3.  不要求固定先执行 Discovery。
4.  不要求每个请求都经过全部 Specialist。
5.  原子、确定性的论文处理使用 Basic Paper Tools。
6.  复杂且需要独立 Observe → Decide → Act 循环的任务才封装成 Specialist
    Agent。
7.  三个 Specialist 以 Agent-as-Tool 形式暴露给 SciTraceAgent。
8.  所有 Specialist Result 都返回 SciTraceAgent，由 Supervisor
    重新决策。
9.  用户目标满足后立即 FINISH。
10. 涉及复现可信度、资源来源、环境或科学语义的重要修改必须进入 HITL。
11. 大型论文、Repository、Index、Log、Checkpoint、Artifact 不直接放入
    LangGraph State。
12. V1 不引入 Skills。

------------------------------------------------------------------------

## 3. V1 顶层架构

SciTrace V1 的正式架构为：

``` text
                              User
                               │
                               ▼
                      ┌─────────────────┐
                      │  SciTraceAgent  │
                      │ Supervisor Loop │
                      └────────┬────────┘
                               │
                       choose next action
                               │
       ┌───────────────────────┼───────────────────────┬───────────────────────┐
       │                       │                       │                       │
       ▼                       ▼                       ▼                       ▼
Basic Paper Tools       DiscoveryAgent            TraceAgent           ExecutionAgent
                           as Tool                  as Tool                as Tool
       │                       │                       │                       │
       └───────────────────────┴───────────┬───────────┴───────────────────────┘
                                           │
                                    Structured Result
                                           │
                                           ▼
                                      Update State
                                           │
                                           ▼
                                     SciTraceAgent
                                           │
                              Continue / HITL / FINISH
```

Supervisor 的概念性 Action Space：

``` python
Action = (
    basic_paper_tool(...)
    | discovery_agent(...)
    | trace_agent(...)
    | execution_agent(...)
    | require_user_approval(...)
    | finish(...)
)
```

这里不存在固定的：

``` text
Discovery → Trace → Execution
```

这三个 Specialist 是 SciTraceAgent
可动态选择的平级能力。上述顺序只能是某次任务根据 State 自然形成的
trajectory。

------------------------------------------------------------------------

## 4. SciTraceAgent --- Supervisor / Orchestrator

### 4.1 核心问题

> 用户现在想完成什么？当前 State 已经知道什么？还缺什么？下一步调用哪个
> Tool / Specialist？是否需要用户审批？用户目标是否已经满足？

### 4.2 职责

SciTraceAgent 负责：

-   理解用户意图和任务深度；
-   维护和观察当前任务 State；
-   对简单论文问题直接调用 Basic Paper Tools；
-   动态调用 DiscoveryAgent、TraceAgent、ExecutionAgent；
-   接收 Specialist 的结构化结果；
-   判断是否存在 blocker 或 HITL 条件；
-   判断用户目标是否已经满足；
-   必要时重新规划；
-   生成最终面向用户的回答或报告。

### 4.3 不负责

SciTraceAgent 不应变成万能 Agent。它不负责：

-   大范围自主搜索科研资源；
-   深度 Claim--Code--Experiment 映射；
-   创建和修复实验环境；
-   执行训练或评估实验。

### 4.4 Supervisor Loop

``` text
Observe State
    ↓
Is user goal satisfied?
    ├── Yes → FINISH
    └── No
          ↓
Does next action require approval?
    ├── Yes → HITL
    └── No
          ↓
Choose best next action
    ├── Basic Paper Tool
    ├── DiscoveryAgent
    ├── TraceAgent
    └── ExecutionAgent
          ↓
Structured Observation
          ↓
Update State
          ↓
Return to Supervisor
```

Specialist Result **绝不意味着自动调用下一个 Specialist**。

------------------------------------------------------------------------

## 5. Basic Paper Tools --- 共享基础能力

V1 不设置 `PaperAnalysisAgent`，也不设置 `Paper Analysis Subgraph`。

"论文解析与检索"属于基础设施能力，而不是独立业务 Agent。

建议 Basic Paper Tools：

``` text
paper.resolve
paper.download
paper.parse
paper.extract_metadata
paper.extract_structure
paper.chunk
paper.build_exact_index
paper.build_vector_index
paper.build_hybrid_index
paper.hybrid_search
paper.get_section
paper.get_table
```

典型任务：

``` text
User:
“这篇论文使用了哪些数据集？”

SciTraceAgent
    ↓
paper.resolve
    ↓
paper.parse / ensure_index
    ↓
paper.hybrid_search
    ↓
SciTraceAgent
    ↓
FINISH
```

因此 V1 中不再存在独立的 "Paper Understanding" Specialist。

需要理解某个 Claim 的论文证据时，由 TraceAgent 针对目标 Claim 查询 Paper
Hybrid Index，而不是先运行一个全局 Paper Understanding Agent。

------------------------------------------------------------------------

## 6. DiscoveryAgent --- Research Resource Discovery & Verification Specialist

### 6.1 核心问题

> 与目标论文/实验相关的科研资源在哪里？这些资源是否可信、是否官方？

### 6.2 负责发现

-   Official Repository
-   Author-affiliated Repository
-   Third-party Implementation
-   Project Page
-   Dataset
-   Checkpoint / Pretrained Model
-   Supplementary Material
-   其他复现所需外部资源

### 6.3 资源验证

DiscoveryAgent 不能只返回"搜到了一个 GitHub"。

它需要收集 provenance evidence，例如：

-   论文是否直接链接该 Repository；
-   官方 Project Page 是否链接该 Repository；
-   README 是否包含论文标题、DOI 或 arXiv ID；
-   Repository owner 是否与作者相关；
-   README 是否声明 official implementation；
-   发布时间是否合理；
-   Dataset / Checkpoint 来源是否与论文描述一致。

资源状态：

``` text
official
author_affiliated
third_party
unverified
```

`resource_status` 与 `verification_confidence` 分离。

### 6.4 边界

DiscoveryAgent 不负责：

-   Paper Understanding；
-   Claim 提取与证据链推理；
-   Claim ↔ Code 映射；
-   构建完整 ReproductionPlan；
-   执行实验。

边界口诀：

``` text
“资源在哪里？可信吗？”
→ DiscoveryAgent

“这个 Claim 是怎么被支撑的？”
→ TraceAgent

“现在真的去跑。”
→ ExecutionAgent
```

### 6.5 输出

``` python
class DiscoveryResult(BaseModel):
    official_repository: ResearchResource | None
    repositories: list[ResearchResource]
    datasets: list[ResearchResource]
    checkpoints: list[ResearchResource]
    project_pages: list[ResearchResource]
    supplementary: list[ResearchResource]
    missing_resources: list[str]
    discovery_status: str
    evidence: list[DiscoveryEvidence]
```

------------------------------------------------------------------------

## 7. TraceAgent --- Claim Evidence Tracing & Reproduction Planning Specialist

### 7.1 为什么叫 Trace

这里的 Trace 不是"总结论文"。

它回答：

> 用户关心的 Scientific
> Claim，到底由论文中的哪些证据、代码、配置、数据和实验支撑？

例如：

``` text
Claim:
“Adaptive Fusion improves OA by 2.3%.”
        │
        ├── Paper Evidence: Section 3.2 / Table 4
        ├── Method: Adaptive Fusion
        ├── Code: models/fusion.py
        ├── Config: configs/ablation/fusion.yaml
        ├── Dataset: AID
        ├── Experiment: scripts/run_ablation.py
        └── Metric: OA
```

这就是 SciTrace 所说的 Scientific Claim Traceability。

### 7.2 职责

TraceAgent 负责：

-   确定目标 Scientific Claim；
-   查询 Paper Hybrid Index；
-   必要时建立/查询 Repository Hybrid Index；
-   定位与 Claim 相关的论文原始证据；
-   定位实现 Method 的代码；
-   定位训练/评估入口；
-   定位 Config、Dataset Loader、Checkpoint、Metric；
-   建立 Claim ↔ Paper ↔ Code ↔ Config ↔ Experiment ↔ Metric 证据链；
-   检测论文、代码、配置之间的不一致；
-   识别缺失或模糊的复现信息；
-   判断当前条件是否足以设计复现实验；
-   生成 ReproductionPlan。

### 7.3 不负责

TraceAgent 不负责：

-   广泛搜索外部科研资源；
-   真正安装依赖；
-   创建运行环境；
-   执行训练/评估；
-   为了跑通而修改科学目标。

### 7.4 输出

``` python
class TraceResult(BaseModel):
    claim_id: str
    paper_evidence: list[PaperEvidence]
    code_evidence: list[CodeEvidence]
    experiment_evidence: list[ExperimentEvidence]
    missing_information: list[str]
    inconsistencies: list[str]
```

``` python
class ReproductionPlan(BaseModel):
    claim_id: str
    mode: str  # code_assisted / paper_only
    required_resources: list[str]
    setup_steps: list[str]
    commands: list[str]
    expected_metric: str | None
    expected_value: float | None
    assumptions: list[str]
    blockers: list[str]
```

------------------------------------------------------------------------

## 8. ExecutionAgent --- Reproduction Execution Specialist

### 8.1 核心问题

> 按照已经确定的
> ReproductionPlan，实验实际上能否运行？发生了什么？最终得到什么结果？

### 8.2 职责

ExecutionAgent 负责：

-   创建隔离 Workspace；
-   创建运行环境；
-   检查 Python / CUDA / Framework；
-   安装依赖；
-   准备 Dataset / Checkpoint / Config；
-   执行 ReproductionPlan 中的命令；
-   捕获 stdout / stderr / exit code；
-   收集 runtime 和必要资源信息；
-   对失败进行分类；
-   在 Repair Policy 允许范围内进行有限修复；
-   在 Retry Budget 内重试；
-   收集 Metric、Log、Artifact；
-   输出 ExecutionResult。

失败分类可包括：

``` text
dependency
dataset
checkpoint
configuration
code_bug
hardware
missing_instruction
external_resource
unknown
```

### 8.3 边界

ExecutionAgent 负责报告执行事实：

``` text
命令是否运行
实际得到什么 metric
发生什么错误
做了哪些 repair
产生哪些 artifacts
```

它不应自行宣布：

``` text
“论文已经成功复现”
“Claim 已被证明”
“论文结论错误”
```

这些属于后续 Verification。

### 8.4 输出

``` python
class ExecutionResult(BaseModel):
    status: Literal["success", "failed", "partial"]
    metrics: dict[str, float]
    commands_run: list[str]
    repairs: list[str]
    logs: list[str]
    artifacts: list[str]
    failure_type: str | None
    failure_reason: str | None
```

------------------------------------------------------------------------

## 9. Validator --- 非 Agent

Validator 不作为第四个 Specialist Agent。

``` text
ExecutionResult
      ↓
Validator
      ↓
VerificationResult
```

Validator 以 deterministic/rule-based comparison 为主，必要时辅以结构化
LLM 判断。

需要严格区分三个概念：

``` text
Execution Success
= 代码是否成功运行

Verification
= 实际结果是否满足预先定义的比较标准

Reproducibility Assessment
= 原论文和资源是否提供足够信息，使实验能够独立复现
```

环境失败不等于 Scientific Claim 被证伪。

建议 Verification Status：

``` text
verified
partially_verified
not_verified
not_reproducible
not_tested
```

------------------------------------------------------------------------

## 10. Dynamic Orchestration --- 禁止固定 Pipeline

V1 禁止把架构画成：

``` text
DiscoveryAgent
      ↓
TraceAgent
      ↓
ExecutionAgent
```

正确逻辑是：

``` text
Specialist / Tool Result
        ↓
Update State
        ↓
SciTraceAgent
        ↓
Is user goal satisfied?
   ┌────┴────┐
  Yes        No
   │          │
FINISH    choose next action
```

可能的 trajectory：

简单论文问题：

``` text
User → SciTraceAgent → Basic Paper Tools → SciTraceAgent → FINISH
```

查官方代码：

``` text
User → SciTraceAgent → DiscoveryAgent → SciTraceAgent → FINISH
```

已有 Repo 的 Claim-Code 查询：

``` text
User → SciTraceAgent → TraceAgent → SciTraceAgent → FINISH
```

缺少 Repo 的 Claim-Code 查询：

``` text
User
→ SciTraceAgent
→ DiscoveryAgent
→ SciTraceAgent
→ TraceAgent
→ SciTraceAgent
→ FINISH
```

已有 ReproductionPlan：

``` text
User → SciTraceAgent → ExecutionAgent → SciTraceAgent → FINISH
```

完整复现可能形成：

``` text
SciTraceAgent
→ DiscoveryAgent
→ SciTraceAgent
→ TraceAgent
→ SciTraceAgent
→ ExecutionAgent
→ Validator
→ SciTraceAgent
→ FINISH
```

但这是运行时 trajectory，不是预定义 workflow。

------------------------------------------------------------------------

## 11. Human-in-the-Loop（HITL）

科研复现 Agent 不能为了"跑成功"而静默改变复现条件。

SciTraceAgent 的决策因此至少包括：

``` text
CONTINUE
REQUIRE_USER_APPROVAL
FINISH
```

### 11.1 必须审批：使用非官方实现

如果没有官方 Repository，但 DiscoveryAgent 找到第三方实现：

``` text
DiscoveryAgent
→ third_party candidate
→ SciTraceAgent
→ HITL
```

必须告诉用户：

-   未发现官方实现；
-   找到了哪个第三方实现；
-   与论文关联的证据；
-   resource status / confidence；
-   使用第三方实现对复现可信度的影响。

只有用户批准后才能继续使用。

### 11.2 必须审批：关键依赖或环境修改

例如：

``` text
Paper/Repo:
Python 3.8 + PyTorch 1.8 + CUDA 11.1

Available:
Python 3.13 + PyTorch 2.x + CUDA 12.x
```

如果需要改变：

-   Python major/minor version；
-   PyTorch / TensorFlow 等核心框架版本；
-   CUDA / cuDNN；
-   关键 dependency pin；

必须说明冲突、拟议修改和风险，并请求用户批准。

### 11.3 必须审批：科学相关源代码修改

如果为了兼容或修复需要修改官方代码，并可能影响：

-   模型行为；
-   数据处理；
-   训练逻辑；
-   评估逻辑；
-   数值结果；

必须 HITL。

批准后保存 patch/diff 和修改原因。

### 11.4 必须审批：替代科研资源

例如：

-   官方 checkpoint 不可用 → 第三方 checkpoint；
-   官方 dataset link 失效 → 镜像或其他版本；
-   指定 pretrained model 不可用 → 其他来源权重。

必须说明 provenance 和差异后请求批准。

### 11.5 必须审批：关键参数需要假设

如果缺失：

-   random seed；
-   learning rate；
-   batch size；
-   preprocessing；
-   evaluation split；
-   checkpoint selection rule；
-   threshold；
-   epoch；

且不同选择可能显著影响结论，则不能静默猜测。

用户批准的假设必须进入 `ReproductionPlan.assumptions`。

### 11.6 必须审批：高成本动作

在明显涉及以下情况前请求确认：

-   长时间 GPU 训练；
-   多 GPU / distributed training；
-   大规模 Dataset 下载；
-   大量磁盘占用；
-   付费云资源/API；
-   长时间 benchmark。

### 11.7 必须审批：破坏性动作

例如：

-   修改用户现有环境；
-   uninstall / downgrade 当前环境包；
-   覆盖已有 checkpoint；
-   修改已有 Repository；
-   删除文件；
-   重写用户 Config。

V1 默认优先使用隔离 Workspace 和独立环境。

------------------------------------------------------------------------

## 12. Repair Policy

不是所有 Error 都需要询问用户。

### Level 1 --- Safe / Deterministic

允许自动执行并记录：

-   README 明确要求但漏装的普通依赖；
-   官方资源有限网络重试；
-   创建隔离临时目录；
-   下载论文/Repository 明确指定的官方资源；
-   读取文件、索引、搜索；
-   不改变实验语义的确定性修复。

### Level 2 --- Scientifically Relevant Modification

必须 HITL：

-   使用第三方实现；
-   修改关键 dependency；
-   环境迁移；
-   科学相关代码 patch；
-   替代 checkpoint / dataset source；
-   关键参数假设；
-   高成本执行。

### Level 3 --- Scientific Target Modification

ExecutionAgent 禁止自主执行：

-   更换 Dataset；
-   更换 Model；
-   更换 Method；
-   更换 Metric；
-   更换目标 Claim；
-   改变关键 train/test split；
-   将不同实验冒充原实验；
-   缩减实验后仍宣称严格复现。

如果用户明确希望改变科学目标，Supervisor 应将其视为新的任务或新的
ReproductionPlan，而不是 Repair。

------------------------------------------------------------------------

## 13. 用户拒绝 HITL 后的行为

用户拒绝某项修改并不意味着系统必须立即结束。

``` text
User Rejects
     ↓
SciTraceAgent
     ↓
Is there another valid path?
   ┌────┴────┐
  Yes        No
   │          │
Replan      FINISH
```

例如用户拒绝第三方 Repository：

``` text
Reject third-party repo
        ↓
SciTraceAgent
        ↓
TraceAgent paper-only mode
        ↓
Reproducibility-readiness assessment
```

HITL 的本质是把关键科学决策权留给用户，而不是"发生 Error 就询问"。

------------------------------------------------------------------------

## 14. Paper Hybrid Retrieval

Vector DB 不是 source of truth。

Paper 原始内容需要保留结构与 provenance：

``` python
class PaperChunk(BaseModel):
    chunk_id: str
    text: str
    section: str
    subsection: str | None
    page: int | None
    chunk_type: Literal[
        "paragraph",
        "table",
        "figure_caption",
        "equation",
        "algorithm",
    ]
    source_span: str | None
```

检索：

``` text
Query
  │
  ├── Exact / Keyword / BM25
  │
  └── Vector Search
          ↓
        Merge
          ↓
        Rerank
          ↓
Original Chunks + Provenance
```

Exact Retrieval 适合：

``` text
Table 3
Eq. (7)
92.4%
ResNet-50
batch_size
learning_rate
dataset name
```

Vector Retrieval 适合语义问题：

``` text
哪个实验验证了 robustness？
为什么设计这个 module？
哪个 ablation 支撑该 Claim？
```

------------------------------------------------------------------------

## 15. Repository Hybrid Retrieval

Repository 同样不能只使用 embedding。

``` text
Repository
     ↓
Files / AST / Symbols / Configs
     ↓
┌──────────────────┬──────────────────┐
│ Exact / AST      │ Vector Retrieval │
└──────────────────┴──────────────────┘
             ↓
          Hybrid
             ↓
          Rerank
```

Exact / AST 负责：

-   filename；
-   function/class/symbol；
-   config key；
-   imports；
-   entrypoint；
-   AST relationships。

Vector 负责处理语义命名差异，例如：

``` text
Paper:
“Adaptive Fusion”

Code:
CrossScaleMixer
```

TraceAgent 可以联合：

``` text
Paper Hybrid Index
        ↘
        TraceAgent
        ↗
Repository Hybrid Index
```

------------------------------------------------------------------------

## 16. State、Runtime 与大型数据

原则：

``` text
State
= 当前任务需要共享的业务数据 + Structured Result + Reference ID

Runtime
= Agent 执行所需依赖和基础设施

Storage / Index / Artifact Store
= 大型持久数据
```

不要把以下内容直接塞进 LangGraph State：

-   整篇 PDF；
-   全部 Repository；
-   Embedding；
-   Vector DB；
-   大型日志；
-   Checkpoint；
-   Dataset；
-   大型 Artifact。

建议：

``` python
class SciTraceState(TypedDict):
    user_query: str

    paper_source: str | None
    paper_document_id: str | None
    paper_index_id: str | None

    discovery_result: DiscoveryResult | None

    repository_index_id: str | None

    claims: list[ScientificClaim]

    trace_result: TraceResult | None
    reproduction_plan: ReproductionPlan | None

    execution_result: ExecutionResult | None
    verification_result: ClaimVerification | None

    approvals: list[ApprovalRecord]

    intent: str | None
    current_task: str | None
    final_answer: str | None
```

可以使用：

``` text
ensure_paper_resolved
ensure_paper_index
ensure_discovery
ensure_repo_index
```

先检查 State / Cache，再决定是否重复计算。

------------------------------------------------------------------------

## 17. Approval Record

用户授权不能只存在聊天文本中。

``` python
class ApprovalRecord(BaseModel):
    approval_type: str
    requested_action: str
    reason: str
    risk: str
    user_decision: str
    related_resource_id: str | None = None
```

典型 approval type：

``` text
third_party_repository
dependency_change
environment_migration
source_code_patch
alternative_checkpoint
alternative_dataset
parameter_assumption
high_cost_execution
destructive_action
```

最终报告需要能够追踪：

``` text
Original Condition
      ↓
Problem
      ↓
Proposed Change
      ↓
User Decision
      ↓
Actual Action
      ↓
Impact on Reproduction Provenance
```

------------------------------------------------------------------------

## 18. Reproduction Provenance

不能把"代码跑通"直接写成"论文严格复现成功"。

建议区分：

### Strict Reproduction

使用论文/官方指定资源，没有影响科学语义的修改。

### Assisted Reproduction

主要使用官方资源，但存在用户批准的环境、依赖或代码兼容修复。

### Third-party Reproduction

用户明确批准使用非官方实现或关键第三方资源。

### Alternative Experiment

用户明确改变原始科学目标后形成的新实验。不得描述为原实验严格复现。

### Not Reproducible

在当前资源和约束下无法完成原始复现。

### Not Tested

尚未实际执行。

Provenance 与 Verification Status 是两个维度：

``` text
Provenance:
“这个结果是在什么条件下得到的？”

Verification:
“这个结果是否满足预先定义的验证标准？”
```

------------------------------------------------------------------------

## 19. No-Code 场景

没有官方代码时，SciTrace 不能默认"自己重写整篇论文"。

DiscoveryAgent 应明确：

``` text
official repository: not found
```

如果发现第三方实现：

``` text
→ HITL
→ 用户批准后才能使用
```

如果用户不批准或不存在可靠实现，TraceAgent 可以进入：

``` text
paper_only
```

主要完成：

-   Claim evidence tracing；
-   Method / Experiment specification extraction；
-   missing information；
-   ambiguity；
-   reproducibility gap；
-   independent reproduction readiness；
-   paper-only ReproductionPlan（如果信息足够）。

V1 不承诺 arbitrary paper → full implementation from scratch。

------------------------------------------------------------------------

## 20. Tool 与 Agent-as-Tool

### Tool

原子能力：

``` text
paper.parse
paper.hybrid_search
repo.find_symbol
execution.run_command
```

### Tool Group

工程组织与权限边界：

``` text
Paper Tools
Discovery Tools
Repository Tools
Trace Tools
Execution Tools
Validation Tools
```

Tool Group 不增加自主智能。

### Agent-as-Tool

对 Supervisor 暴露的复杂自主能力：

``` text
DiscoveryAgent
TraceAgent
ExecutionAgent
```

它们内部可以拥有自己的：

``` text
Observe
→ Decide
→ Tool Call
→ Observation
→ Decide
→ Finish
```

V1 原则：

> 能用确定性 Tool 解决的问题，不额外 Agent
> 化；只有需要独立动态决策循环的复杂任务才使用 Agent。

------------------------------------------------------------------------

## 21. Specialist Tool 权限

建议：

``` text
SciTraceAgent
├── Basic Paper Tools
├── DiscoveryAgent-as-Tool
├── TraceAgent-as-Tool
└── ExecutionAgent-as-Tool
```

``` text
DiscoveryAgent
├── Discovery Search Tools
├── Resource Verification Tools
└── Limited Repository Metadata Tools
```

``` text
TraceAgent
├── Paper Retrieval Tools
├── Repository Tools
└── Trace Tools
```

``` text
ExecutionAgent
├── Limited Repository Tools
├── Execution Tools
└── Artifact Tools
```

不要给每个 Agent 所有 Tool。

------------------------------------------------------------------------

## 22. Eval

Eval 从 V1 开始同步建设，而不是项目最后补。

### Discovery

-   Top-1 official resource accuracy
-   Top-k recall
-   no-repo precision
-   resource status classification accuracy

### Claim / Evidence Trace

-   Claim extraction Precision / Recall / F1
-   Evidence Hit@1
-   Evidence Hit@5
-   MRR
-   Claim--Code mapping accuracy

### Reproduction Planning

-   executable plan rate
-   plan completeness
-   unsupported-assumption rate

### Execution

-   environment build success
-   run success
-   repair success
-   unnecessary modification rate

### HITL

-   required-approval detection recall
-   unnecessary-interrupt rate
-   unauthorized modification rate（目标应接近 0）

### Verification

-   verification classification accuracy

### End-to-End

-   hierarchical reproduction score
-   claim-weighted score
-   tokens / cost
-   wall time
-   number of HITL interruptions
-   provenance correctness

------------------------------------------------------------------------

## 23. V1 项目结构

``` text
src/scitrace/
├── graph/
│   ├── state.py
│   ├── builder.py
│   ├── routing.py
│   └── nodes.py
│
├── agents/
│   ├── scitrace_agent.py
│   ├── discovery_agent.py
│   ├── trace_agent.py
│   └── execution_agent.py
│
├── models/
│   ├── paper.py
│   ├── claims.py
│   ├── resources.py
│   ├── experiments.py
│   ├── evidence.py
│   ├── execution.py
│   ├── approval.py
│   └── report.py
│
├── tools/
│   ├── paper/
│   ├── discovery/
│   ├── repository/
│   ├── trace/
│   ├── execution/
│   └── validation/
│
├── indexing/
│   ├── paper_index.py
│   └── repo_index.py
│
├── execution/
├── validation/
└── reporting/
```

V1 不建立：

``` text
skills/
paper_analysis_agent.py
paper_analysis_subgraph.py
```

------------------------------------------------------------------------

## 24. V1 Frozen Decisions

以下决定作为当前 V1 的实现约束：

1.  使用 LangGraph + LangChain。
2.  顶层只有一个 `SciTraceAgent` Supervisor。
3.  SciTraceAgent 是动态 Agent Loop，而不是一次性 Router。
4.  SciTraceAgent 可直接调用 Basic Paper Tools。
5.  V1 不设置 PaperAnalysisAgent。
6.  V1 不设置 Paper Analysis Subgraph。
7.  DiscoveryAgent 不承担 Paper Understanding。
8.  DiscoveryAgent 只负责 Research Resource Discovery & Verification。
9.  TraceAgent 负责 Claim Evidence Tracing & Reproduction Planning。
10. ExecutionAgent 负责 Reproduction Execution。
11. DiscoveryAgent、TraceAgent、ExecutionAgent 均以 Agent-as-Tool 暴露给
    Supervisor。
12. 三个 Specialist 在 Supervisor Action Space 中平级。
13. 不存在固定 `Discovery → Trace → Execution` Pipeline。
14. 每个 Specialist Result 都回到 SciTraceAgent。
15. 每轮返回后重新检查用户目标；满足则立即 FINISH。
16. 简单论文问题优先由 SciTraceAgent + Basic Paper Tools 完成。
17. Paper 使用 Exact + Vector Hybrid Retrieval。
18. Repository 使用 Exact/AST + Vector Hybrid Retrieval。
19. Vector DB 不是 source of truth，必须保留原始 evidence 和
    provenance。
20. 没有官方 Repo 时不能把第三方实现当官方实现。
21. 使用第三方实现前必须 HITL。
22. 关键 dependency / environment 修改必须 HITL。
23. 影响科学行为的 code patch 必须 HITL。
24. 替代 Dataset / Checkpoint / Weight 等关键资源必须 HITL。
25. 关键实验参数需要假设时必须 HITL。
26. 高成本和破坏性动作按风险策略 HITL。
27. Safe deterministic repair 可以自动执行，但必须记录。
28. ExecutionAgent 禁止自主改变 Dataset、Model、Method、Metric、Claim
    或关键实验目标。
29. 用户拒绝审批后，Supervisor 应先判断是否存在合法替代路径，再决定
    FINISH。
30. Validator 不是 Agent。
31. Execution Success、Verification、Reproducibility Assessment
    必须分离。
32. 最终报告必须记录 Reproduction Provenance。
33. 大型数据进入 Storage / Index / Artifact Store，State
    只保存结构化结果和引用。
34. V1 不引入 Skills。
35. Eval 与开发同步进行。

------------------------------------------------------------------------

## 25. 一句话架构

> **SciTrace V1 是一个由 SciTraceAgent 驱动的动态 Supervisor Agent
> Loop：Supervisor 可直接调用 Basic Paper
> Tools，并把科研资源发现与验证、Scientific Claim
> 证据链追踪与复现规划、实验实际执行三类复杂任务分别委派给
> DiscoveryAgent、TraceAgent、ExecutionAgent 三个
> Agent-as-Tool；所有结果回流 Supervisor，由当前 State、用户目标与 HITL
> 风险策略决定下一步或终止。**
