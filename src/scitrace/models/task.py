from typing import Any, Literal

from pydantic import Field

from scitrace.models.core import Record


class Task(Record):
    """任务的持久化摘要。

    Agent 图的临时状态仍由 LangGraph checkpoint 保存；这里仅保留 CLI 恢复、
    报告和权限边界需要的稳定字段，避免任务创建逻辑散落在 CLI 字典中。
    """

    query: str
    status: Literal[
        "created",
        "running",
        "waiting_approval",
        "partial",
        "finished",
        "failed",
    ] = "created"
    local_inputs: list[str] = Field(default_factory=list)
    trusted_project_urls: list[str] = Field(default_factory=list)
    requires_execution: bool = False
    error: str | None = None
    final_answer: str | None = None
    pending_approval: str | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
