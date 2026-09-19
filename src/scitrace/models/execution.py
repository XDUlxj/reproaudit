"""实验真实执行过程与产出模型。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from scitrace.models.base import Record


class MetricOutput(BaseModel):
    """实验实际产生的标量指标。"""

    kind: Literal["metric"] = "metric"
    name: str = Field(min_length=1)
    value: float


class ArtifactOutput(BaseModel):
    """已由 ArtifactStore 持久保存的文件元数据。"""

    kind: Literal["artifact"] = "artifact"
    name: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


ObservedOutput = Annotated[MetricOutput | ArtifactOutput, Field(discriminator="kind")]


class CommandRun(BaseModel):
    """一条命令的实际执行结果，而不是预期命令。"""

    command: str = Field(min_length=1)
    status: Literal["running", "succeeded", "failed", "interrupted"]
    exit_code: int | None = None


class LocalExecutionHandle(BaseModel):
    """本地受控执行环境中的进程标识。"""

    pid: int = Field(gt=0)
    create_time: float = Field(gt=0)


class ExperimentRun(Record):
    """一次正式 ExperimentSpec 的实际执行尝试。"""

    experiment_spec_id: str = Field(min_length=1)
    status: Literal["running", "succeeded", "failed", "interrupted"] = "running"
    execution_handle: LocalExecutionHandle | None = None
    command_runs: list[CommandRun] = Field(default_factory=list)
    outputs: list[ObservedOutput] = Field(default_factory=list)
    logs: list[ArtifactOutput] = Field(default_factory=list)
    error: str | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "ExperimentRun":
        """防止将未结束的 run 伪装成已终态，反之亦然。"""
        if self.status == "running" and self.finished_at is not None:
            raise ValueError("运行中的 ExperimentRun 不能设置 finished_at")
        if self.status != "running" and self.finished_at is None:
            raise ValueError("终态 ExperimentRun 必须设置 finished_at")
        return self
