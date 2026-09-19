# SciTrace V2 --- HITL（Human-in-the-Loop）设计

> 状态：V1 架构定稿\
> 语言：中文\
> 前置文档：`SciTrace_V2_Policy_CN.md`
>
> 本文定义 SciTrace 在需要人工介入时的业务语义、控制边界与
> LangGraph/LangChain
> 实现原则。目标不是让用户频繁审批，而是在**科学语义改变、资源无法自动消歧、执行触及敏感边界、自动预算耗尽**时提供明确的人类决策点。

------------------------------------------------------------------------

# 1. HITL 的定位

SciTrace 是自主科研复现 Agent。

因此 HITL 的原则不是：

``` text
每个重要动作
    ↓
都问用户
```

而是：

``` text
可以安全、确定地自动完成
        ↓
       AUTO

存在需要用户承担的高影响决策
        ↓
       HITL

明确不允许的动作
        ↓
       BLOCK
```

HITL 是 SciTrace 控制层的一部分，不是一个新的 Agent。

不要创建：

``` text
HITLAgent
ApprovalAgent
```

------------------------------------------------------------------------

# 2. Prompt、Routing、Policy、HITL 的边界

四者职责必须分开。

``` text
Prompt
→ 告诉 Agent 应该怎样行动

Routing
→ 下一步应该委派给哪个 Specialist

Policy
→ 某个动作是否合法

HITL
→ 当 Policy 无法自动放行、且需要人的决策时暂停并等待用户
```

完整关系：

``` text
                   SciTraceAgent
                  autonomous loop
                        │
                        ▼
                  proposes action
                        │
                        ▼
                      Policy
                        │
              ┌─────────┼─────────┐
              ▼         ▼         ▼
            ALLOW      HITL      BLOCK
              │         │
              │         ▼
              │     interrupt
              │         │
              │      user decision
              │         │
              └─────────┴──────→ resume
```

Policy 决定"是否需要人"。

HITL 负责"如何暂停、展示问题、接收决定并恢复"。

------------------------------------------------------------------------

# 3. 两类 HITL

SciTrace V1 明确采用两类 HITL：

``` text
HITL
├── Tool-level HITL
│      → HumanInTheLoopMiddleware
│
└── Business-level HITL
       → LangGraph interrupt() + Command(resume=...)
```

两者底层都依赖 LangGraph 的持久化与恢复能力，但抽象层不同。

------------------------------------------------------------------------

# 4. Tool-level HITL

Tool-level HITL 回答：

> "这个即将执行的 Tool Call 是否允许？"

典型对象是具有实际副作用或安全风险的 Tool。

例如：

``` text
ExecutionAgent
    ↓
准备执行敏感 shell command
    ↓
HumanInTheLoopMiddleware
    ↓
用户审批
    ↓
Tool 真正执行
```

适合的场景包括：

-   请求 sudo/root；
-   使用用户私有凭据；
-   访问私有资源；
-   修改 SciTrace workspace 外文件；
-   某些可能影响宿主机环境的命令；
-   其他被 Execution Safety Policy 判定为需要人工审批的 Tool Call。

------------------------------------------------------------------------

# 5. 为什么 Tool-level 使用 HumanInTheLoopMiddleware

对于标准 Tool Call，LangChain 已经提供 HITL Middleware 机制。

概念上：

``` text
Model
  ↓
Tool Call
  ↓
HumanInTheLoopMiddleware
  ↓
interrupt
  ↓
approve / edit / reject
  ↓
Tool execution or cancellation
```

SciTrace 不需要重新实现：

``` text
解析 tool call
提取 tool name
提取 args
生成审批请求
修改 args
拒绝 tool
恢复 tool
```

因此标准敏感 Tool Call 优先使用框架提供的 Middleware。

------------------------------------------------------------------------

# 6. Business-level HITL

Business-level HITL 回答的不是：

> "某个 Tool 能不能调用？"

而是：

> "SciTrace 当前遇到一个业务决策，需要用户选择。"

当前 V1 有三类核心 Business HITL：

``` text
1. Semantic Spec Revision
2. Resource Ambiguity
3. Budget Exhausted
```

它们直接使用：

``` python
interrupt(...)
```

恢复时使用：

``` python
Command(resume=...)
```

------------------------------------------------------------------------

# 7. 为什么业务决策不强行使用 Tool Middleware

例如 AnalysisAgent 提出：

``` text
Dataset A
    ↓
改为
Dataset B
```

这属于：

``` text
Semantic ExperimentSpec Revision
```

用户真正需要回答的是：

> 是否接受新的科研实验定义？

这不是某个 Tool Call 的参数审批。

如果硬包装成：

``` text
approve tool?
```

会破坏业务语义。

因此：

``` text
Tool-level safety
→ HumanInTheLoopMiddleware

Business-level decision
→ interrupt()
```

------------------------------------------------------------------------

# 8. Business HITL 不使用统一 approve/edit/reject

不同业务场景拥有不同决策语义。

不要强行设计：

``` python
class ApprovalDecision:
    action: Literal["approve", "edit", "reject"]
```

然后让所有 HITL 都套进去。

V1 按场景定义 response contract。

------------------------------------------------------------------------

# 9. Semantic Spec Revision HITL

触发条件：

``` text
AnalysisAgent
    ↓
ProposeSpec
    ↓
已有正式 ExperimentSpec
    ↓
Spec Change Policy
    ↓
Semantic Revision
    ↓
HITL
```

应向用户展示至少：

``` text
当前 Spec
修改后的 Spec
具体修改项
AnalysisAgent 修改原因
修改可能造成的科研语义变化
```

用户操作：

``` text
approve
reject
edit
```

------------------------------------------------------------------------

## 9.1 approve

``` text
用户 approve
    ↓
materialize 新 ExperimentSpec
    ↓
parent_spec_id = old_spec.id
    ↓
Persist
    ↓
更新 Main State
    ↓
Agent Loop resume
```

旧 Spec 不修改。

------------------------------------------------------------------------

## 9.2 reject

Reject 不等于：

``` text
Task.failed
```

而是：

``` text
拒绝本次 Spec revision
```

恢复后 Main Agent 根据当前上下文决定：

-   是否要求 AnalysisAgent 寻找其他方案；
-   是否继续 Discovery；
-   是否存在原 Spec 下的其他合法尝试；
-   是否已经无法继续。

只有 Completion Policy 最终判断没有合法继续路径时，Task 才可能 failed。

------------------------------------------------------------------------

## 9.3 edit

用户可以修改 Proposal 中的业务内容。

例如：

``` text
Analysis Proposal:
batch_size = 64
dataset = Dataset B

User:
dataset 仍然使用 Dataset A
```

用户编辑后的结果不能直接原地修改历史 Spec。

仍然应该：

``` text
edited draft
    ↓
validation
    ↓
materialize new ExperimentSpec
    ↓
parent_spec_id = old_spec.id
```

必要时可以重新交给 AnalysisAgent 检查修改后的方案是否内部一致。

------------------------------------------------------------------------

# 10. Resource Ambiguity HITL

触发条件：

``` text
Discovery
    ↓
发现多个候选资源
    ↓
自动 provenance verification
    ↓
仍无法消歧
    ↓
该歧义会实质影响复现实验
    ↓
HITL
```

例如：

``` text
Paper X
  │
  ├── Repository A
  ├── Repository B
  └── Repository C

Discovery 无法可靠判断哪个实现对应目标实验
```

此时用户操作不应该是：

``` text
approve / reject
```

而应该是：

``` text
select(resource)
reject
```

必要时未来可以支持：

``` text
provide_resource
```

即用户直接提供正确 URL/文件。

------------------------------------------------------------------------

## 10.1 用户 select

``` text
select Repository B
    ↓
Resource validation
    ↓
accept ResearchResource
    ↓
Persist
    ↓
merge into Main State.resources
    ↓
resume
```

------------------------------------------------------------------------

## 10.2 用户 reject

Reject 表示：

``` text
这些候选都不接受
```

Main Agent 可以继续：

``` text
Discovery
```

如果没有新的合法发现路径，才进一步进入无法解决流程。

------------------------------------------------------------------------

# 11. Budget Exhausted HITL

触发：

``` text
Execution
    ↓
Analysis
    ↓
Retry
    ↓
...
    ↓
automatic budget exhausted
    ↓
HITL
```

向用户展示：

``` text
已经执行多少次
每次 ExperimentRun 的状态
关键错误 / 输出
Analysis 当前诊断
继续执行的建议
继续执行可能增加的成本
```

用户操作：

``` text
continue
stop
edit_budget
```

------------------------------------------------------------------------

## 11.1 continue

表示允许额外执行。

它不是修改历史 Run，而是允许未来创建新的 ExperimentRun。

------------------------------------------------------------------------

## 11.2 stop

表示：

``` text
用户不允许继续增加自动实验尝试
```

之后由 Completion Policy 根据当前状态决定 Task 最终结果。

不要在 HITL handler 内直接：

``` python
task.status = "failed"
```

------------------------------------------------------------------------

## 11.3 edit_budget

未来可以允许用户指定：

``` text
再允许 N 次
最长再运行 X 时间
GPU budget
cost budget
```

V1 初期可以只实现：

``` text
additional_attempts
```

其他预算维度等真实需求出现后再增加。

------------------------------------------------------------------------

# 12. Tool-level HITL 的用户操作

对于 LangChain 标准 Tool HITL，采用框架的审批语义：

``` text
approve
edit
reject
```

例如：

``` text
command:
sudo apt install xxx
```

### approve

允许原 Tool Call 执行。

### edit

用户修改 Tool arguments 后再执行。

### reject

不执行该 Tool Call，并将拒绝结果反馈给 Agent，使 Agent
可以寻找其他方案。

注意：

``` text
reject tool
≠
Task failed
```

------------------------------------------------------------------------

# 13. HITL 的暂停模型

Business HITL 概念上：

``` python
decision = interrupt({
    "type": "...",
    "context": {...},
    "options": [...],
})
```

执行到 `interrupt()` 后：

``` text
当前 Graph execution 暂停
        ↓
checkpoint 保存状态
        ↓
控制权返回调用方
        ↓
等待用户
```

用户做出决定后：

``` python
Command(resume=user_decision)
```

恢复同一个 thread。

------------------------------------------------------------------------

# 14. thread_id 与 checkpoint

HITL 必须与持久化 checkpointer 配合。

概念上：

``` python
config = {
    "configurable": {
        "thread_id": task_id
    }
}
```

首次运行：

``` python
graph.invoke(input, config=config)
```

发生 interrupt 后，使用同一个 thread：

``` python
graph.invoke(
    Command(resume=decision),
    config=config,
)
```

具体 thread_id 是否直接等于 Task.id，可以在实现阶段决定。

架构要求只有一个：

> 必须能够稳定地把 HITL resume 定位回原来的 SciTrace execution thread。

------------------------------------------------------------------------

# 15. interrupt 的重要语义：节点可能重新执行

这是实现 HITL 时最重要的规则之一。

不要假设：

``` text
interrupt()
返回以后
从 Python 下一行永久继续
```

恢复时，包含 interrupt 的节点可能从节点开头重新执行。

因此：

``` python
def node(state):
    do_side_effect()
    decision = interrupt(...)
```

存在风险：

``` text
第一次执行
→ do_side_effect()

interrupt

resume

节点重新执行
→ do_side_effect() AGAIN
```

所以 `interrupt()` 前不能随意放不可重复的副作用。

------------------------------------------------------------------------

# 16. HITL 节点的副作用规则

推荐：

``` text
prepare decision data
      ↓
interrupt
      ↓
receive decision
      ↓
validate
      ↓
perform side effect
```

不要：

``` text
persist new spec
      ↓
interrupt "是否接受？"
```

正确：

``` text
draft
  ↓
interrupt
  ↓
approve
  ↓
materialize
  ↓
persist
```

------------------------------------------------------------------------

# 17. 幂等性

即使把副作用放到 interrupt 之后，SciTrace 的持久化仍应尽量支持幂等。

原因：

``` text
DB commit
    ↓
process crash
    ↓
checkpoint 尚未完成
    ↓
resume/replay
```

可能造成重复提交。

因此继续遵守 Persistence Boundary：

``` text
Policy/HITL decision
        ↓
materialize
        ↓
idempotent persist / upsert
        ↓
update Main State
        ↓
continue Agent Loop
```

不要依赖"节点绝对只运行一次"。

------------------------------------------------------------------------

# 18. HITL 与 Main State

当前 Main State：

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

V1 暂时不增加：

``` text
waiting_approval
approval_state
pending_hitl
hitl_type
pending_decision
```

原因：

LangGraph interrupt + checkpoint 已经负责保存暂停位置与上下文。

不要把 Runtime 状态重复塞进业务 Main State。

------------------------------------------------------------------------

# 19. HITL 与 Task.status

Task 当前：

``` text
created
running
finished
failed
```

发生 HITL 时：

``` text
Task.status = running
```

即可。

不要重新加入：

``` text
waiting_approval
```

因为：

``` text
waiting_approval
```

描述的是 Graph 当前执行状态，而不是 Task 的最终业务生命周期。

------------------------------------------------------------------------

# 20. HITL 与 Persistence

三层仍然分离：

``` text
LangGraph Checkpointer
→ 保存运行时暂停位置和 State

PostgreSQL
→ 保存 Task / Resource / Spec / Run 等正式业务事实

ArtifactStore
→ 保存日志、结果文件、checkpoint artifact 等大对象
```

HITL interrupt 本身不意味着需要创建新的数据库 Entity。

------------------------------------------------------------------------

# 21. 暂时不创建 ApprovalRecord

V1 不创建：

``` python
class ApprovalRecord(Record):
    ...
```

理由：

当前主要需求是：

``` text
暂停
→ 用户决策
→ 恢复
```

LangGraph checkpoint 已经解决运行时需求。

只有未来明确需要：

``` text
长期审计
谁批准了什么
什么时候批准
原 Proposal 是什么
批准后的内容是什么
```

才引入 ApprovalRecord。

这是业务审计需求，不是 HITL 技术机制的必需品。

------------------------------------------------------------------------

# 22. HITL 与 Agent-as-Tool

Specialist 仍然作为 Agent-as-Tool。

推荐原则：

``` text
Specialist
    ↓
返回 structured result
    ↓
Main / Policy layer
    ↓
判断是否 HITL
```

例如：

``` text
AnalysisAgent
    ↓
ProposeSpec
    ↓
SpecChangePolicy
    ↓
Semantic Revision
    ↓
Business interrupt
```

不建议 AnalysisAgent 自己直接向用户发起业务审批。

这样职责更清晰：

``` text
AnalysisAgent
→ 科研判断

Policy
→ 是否允许自动执行

Main/control layer
→ interrupt / resume
```

------------------------------------------------------------------------

# 23. ExecutionAgent 内部的 Tool HITL

ExecutionAgent 可以调用具有 HITL Middleware 的 Tool。

例如：

``` text
ExecutionAgent
    ↓
run_command(...)
    ↓
Execution Safety classification
    ↓
sensitive
    ↓
HumanInTheLoopMiddleware
    ↓
interrupt
```

这里属于 Tool-level HITL，因此可以发生在 specialist 内部。

这与业务级 HITL 不冲突。

------------------------------------------------------------------------

# 24. 用户拒绝后的原则

所有 HITL 都遵守：

``` text
reject
≠
Task.failed
```

拒绝只是改变当前合法动作集合。

例如：

### Spec reject

``` text
不能采用 Spec V2
→ Main 寻找其他方案
```

### Resource reject

``` text
不能使用候选 Resource A
→ Discovery 继续搜索
```

### Tool reject

``` text
不能执行该敏感 Tool Call
→ ExecutionAgent 尝试替代方案
```

### Budget stop

``` text
不能继续增加 ExperimentRun
→ Completion Policy 判断是否还能完成
```

只有真正不存在合法完成路径时才：

``` text
Task.failed
```

------------------------------------------------------------------------

# 25. HITL response 必须验证

`Command(resume=...)` 返回的数据属于外部输入。

不能默认可信。

每一种 Business HITL 都应有明确的 Pydantic response schema。

概念示例：

``` python
class SpecRevisionDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    edited_spec: ExperimentSpecDraft | None = None
```

``` python
class ResourceSelectionDecision(BaseModel):
    action: Literal["select", "reject"]
    resource_id: str | None = None
```

``` python
class BudgetDecision(BaseModel):
    action: Literal["continue", "stop", "edit_budget"]
    additional_attempts: int | None = None
```

这些是 HITL 输入 DTO，不是 Entity。

实际编码时再根据 UI/API 需求最终确定字段。

------------------------------------------------------------------------

# 26. HITL payload 原则

interrupt 给用户的数据应该：

``` text
足够做决定
但不要把整个 Agent State 暴露出去
```

例如 Spec revision：

``` text
type
summary
reason
changes
old_spec
proposed_spec
allowed_actions
```

而不是：

``` text
全部 messages
全部 internal chain-of-thought
全部 tool traces
整个 checkpoint
```

用户需要业务证据，而不是 Agent 内部推理过程。

------------------------------------------------------------------------

# 27. HITL 不暴露隐藏推理

HITL 可以展示：

``` text
Analysis summary
diagnostic evidence
Run error
resource provenance
Spec diff
verification result
```

但不要设计成：

``` text
展示 LLM chain-of-thought
```

需要的是可审计的结果与证据，不是隐藏推理文本。

------------------------------------------------------------------------

# 28. Business HITL 建议的数据流

``` text
Specialist Result
       ↓
Policy
       ↓
REQUIRE_HITL
       ↓
build typed HITL request
       ↓
interrupt(request)
       ↓
checkpoint
       ↓
USER
       ↓
Command(resume=response)
       ↓
validate response
       ↓
apply decision
       ↓
persist formal business fact if needed
       ↓
update Main State
       ↓
continue autonomous loop
```

------------------------------------------------------------------------

# 29. Spec Revision 完整示例

``` text
Task
 ↓
Spec V1
 ↓
Run 1
 ↓
failed: OOM
 ↓
AnalysisAgent
 ↓
ProposeSpec V2
 ↓
change classification
 ↓
如果仅 batch_size 64 → 32
 ↓
Operational
 ↓
AUTO materialize

-------------------------------

如果 Dataset A → Dataset B
 ↓
Semantic
 ↓
interrupt
 ↓
用户 approve
 ↓
materialize Spec V2
 ↓
parent_spec_id = Spec V1.id
 ↓
Execution
```

------------------------------------------------------------------------

# 30. Resource Ambiguity 完整示例

``` text
Analysis
 ↓
NeedResources(repository)
 ↓
required_specialist = discovery
 ↓
DiscoveryAgent
 ↓
A / B / C repositories
 ↓
自动验证
 ↓
仍然无法消歧
 ↓
Resource Trust Policy
 ↓
REQUIRE_HITL
 ↓
interrupt
 ↓
用户 select B
 ↓
validate B
 ↓
persist ResearchResource B
 ↓
Main State.resources merge B
 ↓
required_specialist = analysis
 ↓
AnalysisAgent
```

------------------------------------------------------------------------

# 31. Budget Exhausted 完整示例

``` text
Run 1 failed
 ↓
Analysis
 ↓
operational fix
 ↓
Run 2 failed
 ↓
Analysis
 ↓
operational fix
 ↓
...
 ↓
automatic budget exhausted
 ↓
interrupt
 ↓
用户：
    continue / stop / edit_budget
```

如果：

``` text
continue
```

则允许新的 Run。

如果：

``` text
stop
```

则禁止继续创建 Run，由 Completion Policy 决定 Task 后续。

------------------------------------------------------------------------

# 32. Tool Safety 完整示例

``` text
ExecutionAgent
 ↓
需要普通：
python evaluate.py
 ↓
Execution Safety
 ↓
AUTO
 ↓
execute

-------------------------------

ExecutionAgent
 ↓
需要：
sudo apt install ...
 ↓
Execution Safety
 ↓
HITL
 ↓
HumanInTheLoopMiddleware
 ↓
用户 approve / edit / reject
```

------------------------------------------------------------------------

# 33. 不要构建统一 HITL God Object

暂时不要创建：

``` python
class HITLRequest:
    type: str
    payload: dict[str, Any]

class HITLResponse:
    action: str
    payload: dict[str, Any]
```

这种设计虽然"通用"，但会损失类型语义。

优先：

``` text
SpecRevisionRequest / Decision
ResourceSelectionRequest / Decision
BudgetRequest / Decision
```

等真实业务模式稳定后，再考虑抽象公共接口。

------------------------------------------------------------------------

# 34. V1 HITL 不变量

以下规则可以钉死：

1.  HITL 不是 Agent。
2.  HITL 不是默认流程，只处理必须由人决定的边界。
3.  Tool-level HITL 优先使用 `HumanInTheLoopMiddleware`。
4.  Business-level HITL 使用 LangGraph `interrupt()` + resume。
5.  Semantic Spec Revision 必须 HITL。
6.  Resource 无法自动消歧且会影响实验语义时必须 HITL。
7.  自动 ExperimentRun budget 耗尽后继续执行必须 HITL。
8.  敏感 Tool Call 根据 Execution Safety Policy 进入 HITL。
9.  不同 Business HITL 使用各自的结构化 response contract。
10. 用户 reject 不等于 Task failed。
11. HITL 等待期间 Task 可以保持 running。
12. Main State 不增加 `waiting_approval` 等重复 runtime 字段。
13. V1 不创建 ApprovalRecord。
14. `interrupt()` 前避免不可重复副作用。
15. 外部副作用和业务持久化尽量保证幂等。
16. Resume 数据必须经过 schema validation。
17. Specialist 的业务结果先返回 Main/Policy，再决定是否业务 HITL。
18. 用户只看到决策所需的结构化事实和证据，不暴露隐藏推理。
19. Business HITL 后产生的新正式业务对象仍遵循 Persistence Boundary。
20. HITL 不负责最终决定 Task finished/failed；Completion Policy 负责。

------------------------------------------------------------------------

# 35. 暂时不要确定的实现细节

以下内容留到编码阶段：

-   Business HITL 节点具体叫什么；
-   thread_id 是否直接使用 task_id；
-   checkpointer 最终使用 PostgreSQL 还是其他实现；
-   前端/CLI 如何渲染 interrupt payload；
-   Tool-level HITL 的具体 tool 列表；
-   `edit` UI 如何展示 Spec；
-   ApprovalRecord 是否在后续版本加入；
-   additional_attempts 默认值；
-   通用 HITL interface 是否值得抽象。

这些不会阻塞下一阶段架构设计。

------------------------------------------------------------------------

# 36. 与 SciTrace 整体架构的关系

当前整体控制结构：

``` text
                         User
                          │
                          ▼
                    SciTraceAgent
                   autonomous loop
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
       DiscoveryAgent AnalysisAgent ExecutionAgent
        agent-as-tool  agent-as-tool  agent-as-tool
            │             │             │
            └─────────────┼─────────────┘
                          ▼
                     structured result
                          │
                          ▼
                    Main / Policy
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
           AUTO          HITL         BLOCK
             │            │
             │       interrupt/checkpoint
             │            │
             │           User
             │            │
             └────────────┴── resume
                          │
                          ▼
                    autonomous loop
```

Tool-level HITL 可以发生在 specialist 的具体 Tool Call 内部。

------------------------------------------------------------------------

# 37. 至此控制层的职责

``` text
Agent
→ 推理和选择动作

Specialist
→ 专业领域工作

Routing
→ 控制下一次必要委派

Policy
→ 判断动作是否合法

HITL
→ 必要时把决策权交给用户

Checkpointer
→ 保存可恢复的运行时状态

PostgreSQL
→ 保存正式业务事实

ArtifactStore
→ 保存大型运行产物
```

这些职责不要互相吞并。

------------------------------------------------------------------------

# 38. 下一阶段

至此可以认为：

``` text
Core Entities          ✓
Specialist Contracts   ✓
Main State             ✓
Agent-as-Tool          ✓
Persistence Boundary   ✓
Routing                ✓
Policy                 ✓
HITL                    ✓
```

下一阶段进入：

``` text
Tool Architecture
```

建议顺序：

``` text
1. 先定义 Service / Tool / Agent 的边界
2. DiscoveryAgent tools
3. AnalysisAgent tools
4. ExecutionAgent tools
5. SciTraceAgent 自身 tools
6. Tool Runtime / context / artifact handling
7. Observability
8. Eval
```

不要先写几十个 Tool。先明确每个 Agent
真正需要哪些能力，再设计最小工具集。

------------------------------------------------------------------------

# 39. 官方参考

LangChain / LangGraph 官方文档：

-   Human-in-the-Loop Middleware\
    https://docs.langchain.com/oss/python/langchain/human-in-the-loop

-   LangGraph Interrupts\
    https://docs.langchain.com/oss/python/langgraph/interrupts

-   LangGraph Persistence\
    https://docs.langchain.com/oss/python/langgraph/persistence

-   LangGraph Durable Execution\
    https://docs.langchain.com/oss/python/langgraph/durable-execution

-   LangChain Middleware Overview\
    https://docs.langchain.com/oss/python/langchain/middleware/overview

-   LangChain Subagents\
    https://docs.langchain.com/oss/python/langchain/multi-agent/subagents

> 说明：LangChain/LangGraph 提供
> interrupt、resume、checkpointer、middleware 等控制机制；Spec
> Revision、Resource Ambiguity、Budget 等 HITL 触发规则属于 SciTrace
> 自身业务设计。
