"""现有领域 Entity 对应的 SQLAlchemy 表。"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SciTrace 业务表的声明式基类。"""


# PostgreSQL 使用可索引、可操作的 JSONB；SQLite 降级时使用原生 JSON 兼容类型。
ENTITY_PAYLOAD_TYPE = JSON().with_variant(JSONB(), "postgresql")


class RecordColumns:
    """所有持久化 Entity 共享的列。"""

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(ENTITY_PAYLOAD_TYPE, nullable=False)


class TaskRow(RecordColumns, Base):
    __tablename__ = "tasks"

    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResourceRow(RecordColumns, Base):
    __tablename__ = "research_resources"

    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class ExperimentSpecRow(RecordColumns, Base):
    __tablename__ = "experiment_specs"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    parent_spec_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiment_specs.id", ondelete="RESTRICT"), nullable=True
    )


class ExperimentRunRow(RecordColumns, Base):
    __tablename__ = "experiment_runs"

    experiment_spec_id: Mapped[str] = mapped_column(
        ForeignKey("experiment_specs.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)


class TaskResourceRow(Base):
    """Task 与已接受 ResearchResource 的多对多关系。"""

    __tablename__ = "task_resources"
    __table_args__ = (UniqueConstraint("task_id", "resource_id"),)

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("research_resources.id", ondelete="RESTRICT"), primary_key=True
    )
