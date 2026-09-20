
```Plain texy
DiscoveryAgent
State  → DiscoveryResult

AnalysisAgent
State  → AnalysisResult
          ├─ KeepSpec
          └─ ProposalNewSpec

ExecutionAgent
State  → ExecutionResult
          ├─ ExecutionSucceeded
          └─ ExecutionFailed
```
# Discovery

## 输入

调用时 wrapper 为 DiscoveryAgent 提供标准 message state。`task_id`、当前资源和委派目标
属于 invocation input/runtime context，不为方便而复制成自定义 Specialist State。

## 输出

```python
class ResourceSummary(BaseModel):
    """本次 Discovery 调用新增资源的统计摘要。"""

    paper_count: int = 0
    repository_count: int = 0
    dataset_count: int = 0
    model_count: int = 0
    

class DiscoveryResult(BaseModel):
    """DiscoveryAgent 单次调用的结构化结果。"""

    discovered_resources: list[ResearchResource] = Field(
        default_factory=list
    )
    summary: ResourceSummary # 并且后续还要更新主图的state
```

# Analysis


```python
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from scitrace.models.experiment import OutputRequirement


class ResourceRequirement(BaseModel):
    """AnalysisAgent 判断仍然缺少的科研资源。"""

    # 缺少哪一类资源
    kind: Literal[
        "paper",
        "repository",
        "dataset",
        "model",
    ]

    # 对缺失资源的具体要求
    # 例如：
    # "Official implementation repository for the target method"
    # "Official pretrained checkpoint used by the target experiment"
    description: str


class ExperimentSpecDraft(BaseModel):
    """AnalysisAgent 构造的、尚未正式采用的实验方案。"""

    # 本实验希望完成什么科研目标
    goal: str

    # ExecutionAgent 执行该实验真正需要的科研资源
    resource_ids: list[str] = Field(default_factory=list)

    # AnalysisAgent 根据论文、代码、配置等信息解析出的执行命令
    commands: list[str] = Field(min_length=1)

    # ExecutionAgent 至少需要收集的实验结果
    outputs: list[OutputRequirement] = Field(default_factory=list)


class ExperimentSpecProposal(BaseModel):
    """AnalysisAgent 提出的 ExperimentSpec 候选方案。"""

    # 尚未 materialize 的实验方案
    spec: ExperimentSpecDraft

    # 为什么提出这一实验方案
    rationale: str


class NeedResources(BaseModel):
    """
    当前科研资源不足。

    AnalysisAgent 无法在现有资源基础上可靠地继续构建、
    修订或验证实验，因此需要 SciTraceAgent 再次调用
    DiscoveryAgent 获取新的科研资源。
    """

    action: Literal["need_resources"] = "need_resources"

    # 具体缺少哪些科研资源
    missing: list[ResourceRequirement]

    # 给 SciTraceAgent / ToolMessage 使用的分析结论摘要
    summary: str


class ProposeSpec(BaseModel):
    """
    AnalysisAgent 提出新的实验方案。

    既可以用于第一次创建 ExperimentSpec：
        None -> spec_001

    也可以用于已有 ExperimentSpec 的修订：
        spec_001 -> spec_002

    Proposal 本身不是正式 ExperimentSpec。
    后续需要经过 SpecChangePolicy / HITL（如果需要），
    再 materialize 为正式 ExperimentSpec。
    """

    action: Literal["propose_spec"] = "propose_spec"

    # AnalysisAgent 提出的候选实验方案
    proposal: ExperimentSpecProposal

    # 给 SciTraceAgent / ToolMessage 使用的分析结论摘要
    summary: str


class KeepSpec(BaseModel):
    """
    当前 ExperimentSpec 仍然有效。

    AnalysisAgent 检查当前资源、ExperimentSpec 和
    ExperimentRun 后，没有发现有证据支持修改实验方案。

    KeepSpec 只表示“Spec 不需要修改”，
    不代表 AnalysisAgent 自己决定重新执行实验。
    是否重新调用 ExecutionAgent 由 SciTraceAgent / Policy 决定。
    """

    action: Literal["keep_spec"] = "keep_spec"

    # 为什么当前 Spec 可以继续使用
    summary: str


class GoalSatisfied(BaseModel):
    """
    当前科研目标已经满足。

    通常出现在 ExperimentRun 成功之后。

    AnalysisAgent 根据：
        - 科研目标
        - reference result
        - reproduction criterion
        - ExperimentRun observed outputs

    判断当前实验已经满足预定义的复现判据。

    具体数值比较应尽量由 deterministic verifier 完成，
    而不是让 LLM 主观判断“结果是否足够接近”。
    """

    action: Literal["goal_satisfied"] = "goal_satisfied"

    # 为什么可以认为当前科研目标已经满足
    summary: str


class UnableToResolve(BaseModel):
    """
    AnalysisAgent 无法可靠确定进一步的恢复方案。

    典型情况：
        - 实验结果没有满足复现目标
        - 已有资源看起来完整
        - 当前 ExperimentSpec 没有发现明确错误
        - 没有足够证据支持继续修改参数或实验方案

    此时不应该让 Agent 无限猜测参数并重复实验，
    而应该将控制权交还 SciTraceAgent，
    由其决定 HITL 或结束 Task。
    """

    action: Literal["unable_to_resolve"] = "unable_to_resolve"

    # 为什么无法继续可靠恢复
    summary: str


AnalysisResult = Annotated[
    NeedResources
    | ProposeSpec
    | KeepSpec
    | GoalSatisfied
    | UnableToResolve,
    Field(discriminator="action"),
]
```

# Execution

```python
class ExecutionSucceeded(BaseModel):
    status: Literal["succeeded"] = "succeeded"

    experiment_run_id: str

    outputs: list[ObservedOutput] = Field(default_factory=list)


class ExecutionFailed(BaseModel):
    status: Literal["failed"] = "failed"

    experiment_run_id: str

    outputs: list[ObservedOutput] = Field(default_factory=list)

    error: str


class ExecutionInterrupted(BaseModel):
    status: Literal["interrupted"] = "interrupted"

    experiment_run_id: str

    outputs: list[ObservedOutput] = Field(default_factory=list)

    summary: str


ExecutionResult = Annotated[
    ExecutionSucceeded
    | ExecutionFailed
    | ExecutionInterrupted,
    Field(discriminator="status"),
]
```
