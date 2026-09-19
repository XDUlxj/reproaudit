"""用户科研请求的领域模型。"""

from typing import Literal

from pydantic import Field

from scitrace.models.base import Record


class Task(Record):
    """用户提交给 SciTrace 的一次完整科研请求。"""

    query: str = Field(min_length=1, description="用户的原始科研请求")
    attachment_ids: list[str] = Field(default_factory=list, description="用户提供的附件标识")
    status: Literal["created", "running", "finished", "failed"] = "created"
    answer: str | None = None
