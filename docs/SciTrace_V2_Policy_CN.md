# SciTrace V2 --- Policy 与 HITL 规划

> 状态：V1 架构规划稿\
> 目标：明确 SciTrace 中哪些规则必须由程序强制保证，哪些情况允许 Agent
> 自主处理，哪些情况必须进入 Human-in-the-Loop（HITL）。
>
> 本文只定义 **Policy / HITL 的业务语义与边界**。具体
> Middleware、Tool、Repository API 等实现细节在编码阶段再确定。

------------------------------------------------------------------------

## 1. Policy 是什么

SciTrace 的主控仍然是自主 Agent Loop。LLM
可以决定下一步做什么，但有些规则不能依赖 Prompt 或模型"自觉遵守"。

这些必须始终成立的规则称为 **业务不变量（Business Invariant）**。

例如：

``` text
LLM 想启动实验
      ↓
是否存在正式 ExperimentSpec？
      ├── 否 → 禁止执行
      └── 是 → 继续检查
```

因此三类控制机制必须分开：

``` text
Prompt
→ 告诉 LLM “应该怎样做”

Routing
→ 决定当前应该把任务委派给哪个 specialist
→ 当前设计：自主 Agent Loop + required_specialist

Policy
→ 判断某个动作是否允许发生
→ 必须由确定性代码兜底
```

Policy 不应该做成另一个
`PolicyAgent`。能确定性判断的规则，应优先由普通代码、validator、service
或 middleware/tool guard 实现。

------------------------------------------------------------------------

# 2. 总体 Policy 分类

SciTrace V1 规划五类 Policy：

``` text
Policy
├── 1. Spec Policy
│      ExperimentSpec 什么时候可以正式采用？
│
├── 2. Execution Policy
│      什么条件下允许启动一次 ExperimentRun？
│
├── 3. Resource Trust Policy
│      Discovery 找到的资源什么时候可以被正式接受？
│
├── 4. Retry / Budget Policy
│      失败后可以自动修复和重跑到什么程度？
│
└── 5. Completion Policy
       什么情况下 Task 可以 finished / failed？
```

另有一个与 Execution Policy 紧密相关但职责独立的：

``` text
Execution Safety Policy
→ 某个实际执行动作是否允许在当前运行环境发生？
```

------------------------------------------------------------------------

# 3. Spec Policy

## 3.1 核心边界

AnalysisAgent 产生的是：

``` text
ExperimentSpecDraft
```

它不是正式的：

``` text
ExperimentSpec
```

正式 Spec 必须经过 materialization。

``` text
AnalysisAgent
    ↓
ProposeSpec
    ↓
ExperimentSpecDraft
    ↓
Spec Policy
    ↓
AUTO / HITL / BLOCK
    ↓
ExperimentSpec
```

------------------------------------------------------------------------

## 3.2 首次 Spec

如果当前 Task 尚不存在正式 `ExperimentSpec`：

``` text
首次 ProposeSpec
      ↓
基础合法性检查
      ↓
通过
      ↓
自动 materialize
```

V1 默认 **不要求用户审批首次 Spec**。

原因不是"第一次一定正确"，而是第一次 Spec
是系统根据论文、仓库、数据和用户目标建立的初始执行基线。只要没有歧义或高风险问题，让用户逐项批准默认参数会显著降低自主性。

首次 Spec 仍必须通过确定性 validation，例如：

-   `goal` 合法；
-   `commands` 非空；
-   `resource_ids` 能解析到已接受的 `ResearchResource`；
-   `VerificationCriterion` 结构合法；
-   不存在明显无法执行的结构错误。

这些属于 validation，不属于 HITL。

------------------------------------------------------------------------

## 3.3 后续 Spec revision

如果已经存在正式 Spec：

``` text
Spec V1
  ↓
Execution
  ↓
失败 / 结果不满足目标
  ↓
Analysis diagnosis
  ↓
ProposeSpec V2
```

此时不能简单覆盖 V1。

必须创建新版本：

``` text
Spec V1
id = A
parent_spec_id = None

Spec V2
id = B
parent_spec_id = A
```

旧 Spec 保留为历史记录。

------------------------------------------------------------------------

## 3.4 Operational Revision 与 Semantic Revision

后续 revision 先分类：

``` text
ProposeSpec revision
        ↓
Spec Change Classification
        │
        ├── Operational Revision
        │       → 默认自动 materialize
        │
        └── Semantic Revision
                → HITL
```

### Operational Revision

只解决工程运行问题，不实质改变科研实验定义。

典型例子：

-   batch size 因 OOM 从 64 改成 32，且不改变实验语义；
-   `num_workers` 调整；
-   修正本地路径；
-   调整缓存目录；
-   增加合理 timeout；
-   修复启动命令语法；
-   适配当前 CUDA / Python 环境；
-   等价的启动方式调整。

默认：

``` text
AUTO
```

### Semantic Revision

会改变实验的科学含义、目标或验证标准。

典型例子：

-   更换 dataset；
-   更换 model architecture；
-   更换会改变实验定义的 checkpoint；
-   修改关键训练/推理超参数；
-   改变目标 metric；
-   改变实验目标；
-   修改 VerificationCriterion；
-   降低原有复现要求；
-   使用与论文实验定义不同的方法替代原方案。

默认：

``` text
REQUIRE HITL
```

------------------------------------------------------------------------

## 3.5 VerificationCriterion 的特殊规则

VerificationCriterion 原则上必须在执行前确定。

禁止：

``` text
先看到结果
   ↓
发现没有达到目标
   ↓
偷偷降低 tolerance
   ↓
宣布复现成功
```

如果执行后确实发现判据定义有误：

``` text
提出新的 ExperimentSpec revision
        ↓
说明为什么修改 criterion
        ↓
HITL
        ↓
生成新的正式 Spec
```

不得原地篡改历史 Spec。

------------------------------------------------------------------------

# 4. Execution Policy

Execution Policy 回答：

> "现在是否允许开始一次新的 ExperimentRun？"

它不回答：

> "这个实验最终能不能跑成功？"

后者属于 ExecutionAgent 的实际执行职责。

------------------------------------------------------------------------

## 4.1 Formal Spec invariant

没有正式 `ExperimentSpec`，禁止创建新的 ExperimentRun。

``` text
experiment_spec is None
        ↓
      BLOCK
```

`ExperimentSpecDraft` 不能直接执行。

------------------------------------------------------------------------

## 4.2 Resource invariant

Spec 引用的 `resource_ids` 必须能够解析到有效的 `ResearchResource`。

``` text
ExperimentSpec.resource_ids
          ↓
ResourceStore / PostgreSQL
          ↓
全部存在？
   ├── 否 → BLOCK / 回到资源解决流程
   └── 是 → 继续
```

这里检查的是
**资源身份和引用是否有效**，不是要求资源已经全部下载到本地。

例如：

``` text
DatasetResource
location = Hugging Face / Web
```

仍然可以是有效资源。

真正的下载、环境准备、依赖安装由 ExecutionAgent 负责。

------------------------------------------------------------------------

## 4.3 Budget invariant

创建新的 Run 之前必须通过 Retry / Budget Policy。

``` text
can_start_new_run(task, spec)?
        ├── yes → continue
        └── no  → STOP / HITL
```

具体规则见第 7 节。

------------------------------------------------------------------------

## 4.4 Execution Safety

普通科研复现动作应尽量自动化，但不能让 Agent 获得无限制宿主机权限。

建议 V1 按风险分级：

  行为                                   默认策略
  -------------------------------------- --------------
  clone/read 公开 repository             AUTO
  下载公开 dataset                       AUTO
  下载公开 model weights                 AUTO
  创建 SciTrace workspace                AUTO
  创建项目虚拟环境                       AUTO
  安装普通项目依赖                       AUTO
  在受控 workspace 内运行训练/评测脚本   AUTO
  写 workspace 内实验输出                AUTO
  删除 workspace 内明确的临时文件        AUTO
  使用用户私有凭据或私有资源             HITL
  修改 workspace 外用户文件              HITL
  修改宿主机系统配置                     HITL / BLOCK
  请求 sudo/root                         HITL / BLOCK
  删除 workspace 外文件                  BLOCK
  明显破坏性 shell 操作                  BLOCK

最终的命令安全分类器在 Execution tools
设计阶段实现，不在当前阶段过度设计。

------------------------------------------------------------------------

## 4.5 Execution Policy 不做什么

不要把以下问题全部做成 Execution 前置检查：

-   CUDA 是否最终足够；
-   dependency 是否真的兼容；
-   数据下载是否一定成功；
-   repo 脚本是否存在运行时 bug；
-   训练是否收敛；
-   实验结果是否达到论文值。

职责边界：

``` text
Execution Policy
→ 允不允许尝试？

ExecutionAgent
→ 实际能不能跑？

AnalysisAgent + Verifier
→ 跑出来是否满足科研目标？
```

------------------------------------------------------------------------

# 5. Resource Trust Policy

Resource Trust Policy 回答：

> "Discovery 找到的这个对象，是否足以被 SciTrace 当作一个正式科研资源？"

它不回答：

> "运行这个资源是否安全？"

后者属于 Execution Safety。

------------------------------------------------------------------------

## 5.1 Search Result ≠ ResearchResource

搜索结果只是候选。

``` text
Search Result
    ↓
Candidate
    ↓
Identity / provenance verification
    ↓
accepted
    ↓
ResearchResource
    ↓
Persist
```

V1 不需要创建独立的 `ResourceCandidate` Entity。

候选可以只是 DiscoveryAgent 内部状态或 Tool Result。

------------------------------------------------------------------------

## 5.2 优先可验证 provenance

### Paper

优先验证：

-   DOI；
-   arXiv ID；
-   title；
-   authors；
-   publication metadata。

### Repository

可以使用：

-   论文正文直接链接；
-   官方 project page 链接；
-   README 引用对应论文；
-   作者/组织关系；
-   repo 引用 DOI / arXiv；
-   release / commit 信息。

### Dataset

可以使用：

-   论文明确给出的数据集；
-   官方 dataset 页面；
-   官方 provider；
-   官方 repo README 指向的下载源。

### Model

可以使用：

-   官方 repo 指向的 checkpoint；
-   作者/组织发布的 model；
-   paper/project page 指向的模型资源。

------------------------------------------------------------------------

## 5.3 不使用简单 `official: bool`

暂不向 `ResearchResource` 增加：

``` text
official
trusted
verified
confidence
```

原因：

``` text
Repository A
```

与：

``` text
Repository A 是 Paper X 的官方实现
```

不是同一种事实。

后者本质上包含 provenance / relation 语义。

V1 先通过 Discovery 的验证过程和来源 metadata 保留必要信息。等实际
Discovery tools
落地后，再根据真实稳定数据决定是否提升成强字段或独立关系模型。

------------------------------------------------------------------------

## 5.4 第三方资源不是天然禁止

优先级：

``` text
直接来源 / 作者 / 官方项目资源
            ↓ preferred

经过验证的第三方资源
            ↓ usable when needed

无法验证或存在重大歧义的资源
            ↓ continue discovery / HITL
```

没有官方 repo 时，经过验证的第三方 reproduction repo 可以被使用。

但不能把第三方资源描述成"官方资源"。

------------------------------------------------------------------------

## 5.5 Resource HITL

不要：

``` text
发现外部资源
→ 每次都问用户
```

只有当：

``` text
资源身份存在重大歧义
        +
会实质改变复现实验
        +
Discovery 无法继续自动消歧
```

才进入 HITL。

例如：

``` text
论文无官方 repo
    ↓
找到三个互相冲突的第三方实现
    ↓
无法确定哪个实现对应目标实验
    ↓
HITL
```

------------------------------------------------------------------------

# 6. Resource Trust 与 Execution Safety 的区别

必须保持：

``` text
Resource Trust
    ≠
Execution Safety
```

例如一个论文作者的官方 GitHub repository：

``` text
科研来源：
高度可信

代码运行安全：
仍然需要受控执行环境和安全规则
```

"官方"不是代码安全证明。

反过来，一个第三方 repo：

``` text
可能可以安全执行
```

但不代表：

``` text
它就是论文官方实现
```

两个维度不能混用。

------------------------------------------------------------------------

# 7. Retry / Budget Policy

这是 SciTrace 能否形成真正自主闭环的关键。

目标不是：

``` text
失败一次 → 立即问用户
```

而是允许：

``` text
Execution
    ↓ failed
Analysis diagnosis
    ↓
可自动修复？
    ↓
Spec operational revision / KeepSpec
    ↓
Execution again
```

同时必须防止：

``` text
Execution
  ↓
Analysis
  ↓
Execution
  ↓
Analysis
  ↓
...
无限循环
```

------------------------------------------------------------------------

## 7.1 区分两种 retry

### Specialist internal recovery

例如 DiscoveryAgent：

``` text
GitHub search tool timeout
    ↓
retry tool
```

属于 specialist 内部恢复。

可使用：

``` text
recovery_count
```

它不是一次新的科研实验。

### Experiment attempt

例如：

``` text
ExperimentRun 1 → OOM
Analysis → operational revision
ExperimentRun 2 → succeeded
```

这是新的实际实验尝试。

不要用 Main State 中的通用 `retry_count` 表示。

应从持久化的：

``` text
ExperimentRun history
```

统计。

------------------------------------------------------------------------

## 7.2 V1 不建议把次数写死在 Entity

不要在：

``` python
Task
ExperimentSpec
ExperimentRun
```

里加入：

``` python
max_retries = 3
```

这属于 Policy configuration，不是这些 Entity 的固有业务事实。

------------------------------------------------------------------------

## 7.3 Budget 应考虑多个维度

后续可以配置：

``` text
attempt budget
wall-clock budget
GPU / compute budget
token budget
monetary budget
```

但 V1 不需要一次实现全部。

最小可用版本建议至少具备：

``` text
最大自动 ExperimentRun 次数
+
单次执行 timeout
```

具体默认数字不要在架构阶段随意拍死，应在真实 benchmark
和项目实验后确定。

------------------------------------------------------------------------

## 7.4 自动 retry 的条件

允许自动继续的典型情况：

``` text
Execution failed
    ↓
Analysis 能给出 evidence-supported diagnosis
    ↓
修复属于 operational revision
    ↓
budget available
    ↓
AUTO RETRY
```

例如：

-   OOM → 合理降低 batch size；
-   本地路径错误 → 修正路径；
-   环境兼容问题 → 调整依赖；
-   启动命令错误 → 修正命令；
-   timeout 合理不足 → 调整 timeout。

------------------------------------------------------------------------

## 7.5 不允许无限"猜参数"

如果 Analysis 无法基于论文、repo、日志或已有证据解释失败：

``` text
UnableToResolve
```

则不能：

``` text
随机改参数
→ 再跑
→ 再随机改
```

应进入：

``` text
HITL / Task failure decision
```

这也是 SciTrace 与"盲目自动调参 Agent"的边界。

------------------------------------------------------------------------

## 7.6 Budget exhausted

当自动执行预算耗尽：

``` text
budget exhausted
       ↓
不要继续创建 ExperimentRun
       ↓
HITL
```

向用户说明：

-   已执行多少次；
-   每次失败/结果情况；
-   Analysis 当前诊断；
-   如果继续，需要进行什么动作；
-   可能增加什么成本或偏离。

用户批准后可以显式增加预算或允许下一次执行。

------------------------------------------------------------------------

# 8. Completion Policy

Completion Policy 回答：

> "Task 什么时候真正 finished，什么时候真正 failed？"

这是 Task 状态的最终业务边界。

------------------------------------------------------------------------

## 8.1 ExperimentRun succeeded ≠ Task finished

必须明确：

``` text
ExperimentRun.status == "succeeded"
```

只表示：

> 命令技术上成功完成。

不表示：

> 科研复现目标已经实现。

例如：

``` text
程序 exit code = 0
accuracy = 72%

论文 reference = 84%
```

Run 是：

``` text
succeeded
```

但科研目标可能：

``` text
not satisfied
```

因此：

``` text
ExecutionSucceeded
        ↓
required_specialist = analysis
        ↓
Analysis / Verification
```

------------------------------------------------------------------------

## 8.2 GoalSatisfied → Task finished

只有 Analysis 基于预先定义的 VerificationCriterion 和 verifier 得出：

``` text
GoalSatisfied
```

或者对于本身不需要执行的简单科研任务，Main Agent
已经完成用户目标，才允许：

``` text
Task.status = "finished"
```

对于"复现实验"类 Task，原则上：

``` text
Run technical success
        ↓
Verification
        ↓
GoalSatisfied
        ↓
Task finished
```

------------------------------------------------------------------------

## 8.3 ExperimentRun failed ≠ Task failed

例如：

``` text
Run 1 failed: CUDA OOM
    ↓
Analysis
    ↓
Operational revision
    ↓
Run 2 succeeded
    ↓
GoalSatisfied
```

最终 Task 应该是：

``` text
finished
```

因此禁止简单传播：

``` text
ExperimentRun.failed
→ Task.failed
```

------------------------------------------------------------------------

## 8.4 Task failed 的条件

Task `failed` 应表示：

> SciTrace
> 在当前约束、资源、预算和用户决策下，最终无法完成用户科研目标。

典型路径：

``` text
AnalysisResult.UnableToResolve
        ↓
没有进一步自动解决方案
        ↓
HITL / policy
        ↓
用户不继续 或 无合法继续路径
        ↓
Task.failed
```

或者：

``` text
必要资源无法获得
        ↓
Discovery 无法解决
        ↓
HITL 后仍无可行资源
        ↓
Task.failed
```

或者：

``` text
必须执行的操作被 Safety Policy BLOCK
        ↓
不存在替代方案
        ↓
Task.failed
```

------------------------------------------------------------------------

## 8.5 HITL 等待不是 failed

等待用户审批期间：

``` text
Task.status
```

不需要增加 `waiting_approval`。

`waiting_approval` 是 Graph/HITL runtime 状态，不是 Task
的长期业务状态。

Task 可以仍保持：

``` text
running
```

LangGraph checkpoint / interrupt 保存具体等待位置。

------------------------------------------------------------------------

# 9. HITL 总原则

HITL 不应该成为 SciTrace 的默认流程。

原则：

> 能由确定性规则安全决定的，不问用户。\
> 能由 Agent 基于充分证据自主解决的，不问用户。\
> 只有涉及高影响歧义、科学语义改变、安全边界或预算扩张时才打断用户。

V1 主要 HITL 场景：

``` text
1. Semantic ExperimentSpec revision
2. 无法自动消歧且会影响实验语义的资源选择
3. 敏感/高风险执行动作
4. 自动实验预算耗尽后继续执行
5. Analysis UnableToResolve 后需要用户决定是否继续/改变目标
```

------------------------------------------------------------------------

# 10. Policy、Routing、HITL 的组合

完整关系：

``` text
                       SciTraceAgent
                      autonomous loop
                            │
                            ▼
                       wants action
                            │
                  ┌─────────┴─────────┐
                  │                   │
             Routing concern      Policy concern
                  │                   │
      谁应该处理下一步？        这个动作允许吗？
                  │                   │
      required_specialist       deterministic guard
                  │                   │
                  │          ┌────────┼────────┐
                  │          ▼        ▼        ▼
                  │        ALLOW     HITL     BLOCK
                  │          │        │
                  └──────────┴────────┘
                            │
                            ▼
                         execute
```

不要把三者合并成一个复杂状态机。

------------------------------------------------------------------------

# 11. 建议的 V1 Policy 形态

当前不建议先造一个通用：

``` python
class PolicyEngine:
    ...
```

也不建议立即统一：

``` python
class PolicyResult:
    decision: Literal["allow", "block", "require_approval"]
```

先用职责明确的确定性函数/service：

``` python
validate_initial_spec(...)
classify_spec_change(...)

can_start_execution(...)
check_execution_safety(...)

accept_resource(...)
needs_resource_disambiguation(...)

can_start_new_run(...)
is_budget_exhausted(...)

can_finish_task(...)
can_fail_task(...)
```

等真正实现后，如果发现大量重复模式，再抽象统一 Policy interface。

YAGNI：先保留清晰业务语义，再抽象框架。

------------------------------------------------------------------------

# 12. 建议的 Policy 决策流程

``` text
                        Agent proposes action
                               │
                               ▼
                      deterministic validation
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
                 invalid    ambiguous    valid
                    │          │          │
                  BLOCK    can Agent      │
                            resolve?       │
                           /      \        │
                         yes      no       │
                          │        │       │
                       continue   HITL     │
                                           ▼
                                      safety/budget
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                            ALLOW         HITL         BLOCK
```

不是所有异常都需要 HITL，也不是所有错误都应该自动重试。

------------------------------------------------------------------------

# 13. 与现有 Entity 的关系

当前核心 Entity 保持：

``` text
Task
ResearchResource
ExperimentSpec
ExperimentRun
```

Policy 设计本身暂时不要求新增 Entity。

以下对象暂时都不需要因为 Policy 而创建：

``` text
PolicyResult Entity
PolicyDecision Entity
ResourceTrust Entity
Retry Entity
Completion Entity
```

未来如果需要长期审计"谁批准了什么"，可以增加：

``` text
ApprovalRecord
```

但应由真实审计需求驱动，而不是为了架构完整性提前创建。

------------------------------------------------------------------------

# 14. 与 Main State 的关系

当前：

``` python
class SciTraceState(MessagesState):
    task_id: str
    resources: list[ResearchResource]
    experiment_spec: ExperimentSpec | None = None
    experiment_run: ExperimentRun | None = None
    required_specialist: Literal[
        "discovery",
        "analysis",
        "execution",
    ] | None = None
```

Policy 暂时不要求加入：

``` text
policy_state
approval_state
retry_count
budget_state
phase
```

真正需要 HITL 时，由 LangGraph checkpoint + interrupt 保存暂停上下文。

实验 attempt 数从持久化 `ExperimentRun` 历史推导。

Policy 配置放独立 configuration，而不是复制到 Main State。

------------------------------------------------------------------------

# 15. 与 Persistence Boundary 的关系

Policy 决定某个对象是否达到业务 commit point。

例如：

``` text
ProposeSpec
    ↓
Spec Policy
    ↓
AUTO / user approve
    ↓
materialize
    ↓
Persist ExperimentSpec
    ↓
Update Main State
```

因此顺序仍然遵守：

``` text
Policy decision
      ↓
materialize
      ↓
PERSIST
      ↓
STATE
      ↓
ToolMessage / continue
```

Policy 不负责数据库实现。

------------------------------------------------------------------------

# 16. 与官方 LangChain / LangGraph 机制的关系

SciTrace 的设计原则与 LangChain/LangGraph 的官方能力边界保持一致：

-   主 Agent + specialist-as-tool：使用 Subagents 模式；
-   动态限制可用工具：使用 Middleware 的 model-call interception /
    dynamic tool selection；
-   HITL：使用 Human-in-the-Loop middleware / interrupt + checkpointer；
-   runtime resume：依赖 LangGraph persistence/checkpoint；
-   side effect / replay 场景：持久化和外部副作用需要考虑幂等性。

Policy 本身是 SciTrace 的业务规则，不应误认为 LangGraph
会自动替项目定义这些业务规则。

------------------------------------------------------------------------

# 17. 当前已经确定的 V1 业务不变量

可以暂时钉死：

### Spec

1.  Draft 不能直接执行。
2.  首次合法 Spec 默认自动 materialize。
3.  后续 Spec revision 不覆盖旧 Spec。
4.  Operational revision 默认可自动 materialize。
5.  Semantic revision 必须 HITL。
6.  VerificationCriterion 原则上必须执行前确定。
7.  执行后修改 VerificationCriterion 必须通过新的 Spec
    revision，不能篡改旧 Spec。

### Execution

8.  没有正式 ExperimentSpec，禁止创建 ExperimentRun。
9.  Spec 引用的资源必须能够解析。
10. 新 Run 必须通过 Budget Policy。
11. 实际执行必须通过 Execution Safety Policy。

### Resource

12. Search Result 不自动等于 ResearchResource。
13. Resource 被接受前必须完成足够的身份/provenance 验证。
14. 第三方资源不是天然禁止。
15. 无法自动解决且影响实验语义的资源歧义进入 HITL。
16. Resource Trust 与 Execution Safety 是两个独立维度。

### Retry / Budget

17. Specialist tool recovery 与 ExperimentRun attempt 分开统计。
18. Experiment attempt 从持久化 Run 历史统计，不在 Main State 维护通用
    retry_count。
19. 有证据支持的 operational recovery 可以在预算内自动重试。
20. 不允许无证据地无限猜参数重跑。
21. 自动预算耗尽后继续运行需要 HITL。

### Completion

22. `ExperimentRun.succeeded` 不等于科学复现成功。
23. `ExperimentRun.failed` 不等于 `Task.failed`。
24. 复现类 Task 在 verification 得到 `GoalSatisfied` 后才能正常
    finished。
25. `Task.failed`
    表示在当前资源、约束、预算和用户决策下最终无法完成目标。
26. 等待 HITL 不需要新增 `Task.waiting_approval` 状态。

------------------------------------------------------------------------

# 18. 暂时不要钉死的内容

以下内容需要真实实现/benchmark 数据后再决定：

-   默认最多自动运行几次；
-   默认单次 timeout；
-   GPU / monetary budget 的具体数字；
-   哪些 dependency installation 算敏感；
-   哪些 shell command 精确属于 BLOCK；
-   Resource provenance 的最终强字段；
-   是否需要 `ApprovalRecord`；
-   是否需要统一 `PolicyResult`；
-   是否需要通用 `PolicyEngine`；
-   semantic revision 的最终自动分类算法。

这些不影响当前架构继续向下推进。

------------------------------------------------------------------------

# 19. 下一步

Policy 规划完成后，建议下一步单独设计：

``` text
SciTrace V2 — HITL
```

重点讨论：

1.  哪些 Tool / action 使用 `HumanInTheLoopMiddleware`；
2.  哪些场景使用 LangGraph `interrupt()`；
3.  approve / reject / edit 如何映射到 Spec revision；
4.  checkpoint + thread_id 如何恢复；
5.  用户拒绝后 Main Agent 如何继续；
6.  如何避免 interrupt 节点重放副作用；
7.  是否需要 ApprovalRecord。

HITL 设计完成后，再进入：

``` text
Tool Architecture
→ Discovery tools
→ Analysis tools
→ Execution tools
→ Services / repositories
→ Eval & observability
```

------------------------------------------------------------------------

# 20. 官方参考

LangChain / LangGraph 官方文档：

-   Subagents\
    https://docs.langchain.com/oss/python/langchain/multi-agent/subagents

-   Middleware Overview\
    https://docs.langchain.com/oss/python/langchain/middleware/overview

-   Custom Middleware\
    https://docs.langchain.com/oss/python/langchain/middleware/custom

-   Human-in-the-Loop Middleware\
    https://docs.langchain.com/oss/python/langchain/human-in-the-loop

-   LangGraph Interrupts\
    https://docs.langchain.com/oss/python/langgraph/interrupts

-   LangGraph Persistence\
    https://docs.langchain.com/oss/python/langgraph/persistence

-   LangGraph Durable Execution\
    https://docs.langchain.com/oss/python/langgraph/durable-execution

> 注：本文中的 Spec/Execution/Resource/Retry/Completion Policy 是
> SciTrace 自身的业务设计；官方文档提供的是
> Agent、Middleware、Interrupt、Persistence 等机制，而不是 SciTrace
> 的业务规则。
