"""领域模型共用的基础类型。"""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    """可持久化领域记录的基类。

    领域模型不负责数据库写入；它们只提供稳定标识和创建时间，实际持久化由
    application/repository 边界在业务提交点完成。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    schema_version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
