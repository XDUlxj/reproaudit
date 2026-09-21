"""领域 Entity 的 SQLAlchemy Repository 实现。"""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from scitrace.models import ExperimentRun, ExperimentSpec, ResearchResource, Task
from scitrace.models.base import Record
from scitrace.persistence.errors import (
    EntityConflictError,
    EntityNotFoundError,
    InvalidLifecycleTransitionError,
)
from scitrace.persistence.tables import (
    ExperimentRunRow,
    ExperimentSpecRow,
    ResourceRow,
    TaskResourceRow,
    TaskRow,
)

EntityT = TypeVar("EntityT", bound=Record)
RowT = TypeVar("RowT")


def _payload(entity: Record) -> dict[str, Any]:
    return entity.model_dump(mode="json")


class _CreateOnlyRepository(Generic[EntityT, RowT]):
    """以稳定 ID 提供可安全重放的 create 语义。"""

    row_type: type[RowT]
    adapter: TypeAdapter[EntityT]

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def _to_row(self, entity: EntityT, **columns: Any) -> RowT:
        return self.row_type(
            id=entity.id,
            schema_version=entity.schema_version,
            created_at=entity.created_at,
            payload=_payload(entity),
            **columns,
        )

    def create(self, entity: EntityT, **columns: Any) -> EntityT:
        """首次写入；相同 ID 与内容可重放，不同内容视为冲突。"""
        with self._session_factory.begin() as session:
            current = session.get(self.row_type, entity.id)
            if current is not None:
                if current.payload != _payload(entity):
                    raise EntityConflictError(f"实体 {entity.id} 已存在且内容不同")
                for name, expected in columns.items():
                    if getattr(current, name) != expected:
                        raise EntityConflictError(f"实体 {entity.id} 已属于其他业务上下文")
                return self.adapter.validate_python(current.payload)
            session.add(self._to_row(entity, **columns))
        return entity

    def get(self, entity_id: str) -> EntityT | None:
        with self._session_factory() as session:
            row = session.get(self.row_type, entity_id)
            return None if row is None else self.adapter.validate_python(row.payload)

    def require(self, entity_id: str) -> EntityT:
        entity = self.get(entity_id)
        if entity is None:
            raise EntityNotFoundError(f"实体 {entity_id} 不存在")
        return entity


class TaskRepository(_CreateOnlyRepository[Task, TaskRow]):
    row_type = TaskRow
    adapter = TypeAdapter(Task)

    def create(self, entity: Task) -> Task:
        return super().create(
            entity,
            status=entity.status,
            query=entity.query,
            answer=entity.answer,
        )

    def update(self, task: Task) -> Task:
        """更新 Task 当前状态，稳定 ID 和创建时间不可变化。"""
        with self._session_factory.begin() as session:
            row = session.get(TaskRow, task.id)
            if row is None:
                raise EntityNotFoundError(f"Task {task.id} 不存在")
            current = self.adapter.validate_python(row.payload)
            if current.created_at != task.created_at or current.schema_version != task.schema_version:
                raise EntityConflictError(f"Task {task.id} 的不可变字段发生变化")
            if current.query != task.query or current.attachment_ids != task.attachment_ids:
                raise EntityConflictError(f"Task {task.id} 的原始请求不可修改")
            allowed = {
                "created": {"created", "running", "failed"},
                "running": {"running", "finished", "failed"},
                "finished": {"finished"},
                "failed": {"failed"},
            }
            if task.status not in allowed[current.status]:
                raise InvalidLifecycleTransitionError(
                    f"Task 不允许从 {current.status} 转换到 {task.status}"
                )
            row.status = task.status
            row.query = task.query
            row.answer = task.answer
            row.payload = _payload(task)
        return task


class ResourceRepository(_CreateOnlyRepository[ResearchResource, ResourceRow]):
    row_type = ResourceRow
    adapter = TypeAdapter(ResearchResource)

    def create(
        self, entity: ResearchResource, *, canonical_key: str
    ) -> ResearchResource:
        return super().create(
            entity,
            kind=entity.kind,
            name=entity.name,
            canonical_key=canonical_key,
        )

    def get_by_canonical_key(self, canonical_key: str) -> ResearchResource | None:
        """按资源科学身份读取正式 ResearchResource。"""
        statement = select(ResourceRow).where(ResourceRow.canonical_key == canonical_key)
        with self._session_factory() as session:
            row = session.scalar(statement)
            return None if row is None else self.adapter.validate_python(row.payload)

    def admit_verified(
        self, resource: ResearchResource, *, canonical_key: str
    ) -> ResearchResource:
        """按 canonical identity 原子准入已验证资源。

        事务内先查询以覆盖通常路径；数据库 UNIQUE 约束负责并发竞态的
        最终仲裁。若另一事务先完成写入，则回读并返回数据库中的资源。
        """
        try:
            with self._session_factory.begin() as session:
                session.add(
                    self._to_row(
                        resource,
                        kind=resource.kind,
                        name=resource.name,
                        canonical_key=canonical_key,
                    )
                )
                session.flush()
        except IntegrityError:
            # 并发写入发生唯一键冲突后，失败事务已回滚；在新事务中回读赢家。
            existing = self.get_by_canonical_key(canonical_key)
            if existing is None:
                raise
            return existing
        return resource

    def attach_to_task(self, task_id: str, resource_id: str) -> None:
        """将已接受资源关联到 Task；重复关联是幂等操作。"""
        with self._session_factory.begin() as session:
            if session.get(TaskRow, task_id) is None:
                raise EntityNotFoundError(f"Task {task_id} 不存在")
            if session.get(ResourceRow, resource_id) is None:
                raise EntityNotFoundError(f"ResearchResource {resource_id} 不存在")
            key = {"task_id": task_id, "resource_id": resource_id}
            if session.get(TaskResourceRow, key) is None:
                session.add(TaskResourceRow(**key))

    def list_for_task(self, task_id: str) -> list[ResearchResource]:
        statement = (
            select(ResourceRow)
            .join(TaskResourceRow, TaskResourceRow.resource_id == ResourceRow.id)
            .where(TaskResourceRow.task_id == task_id)
            .order_by(ResourceRow.created_at, ResourceRow.id)
        )
        with self._session_factory() as session:
            rows: Sequence[ResourceRow] = session.scalars(statement).all()
            return [self.adapter.validate_python(row.payload) for row in rows]


class ExperimentSpecRepository(_CreateOnlyRepository[ExperimentSpec, ExperimentSpecRow]):
    row_type = ExperimentSpecRow
    adapter = TypeAdapter(ExperimentSpec)

    def create(self, entity: ExperimentSpec, *, task_id: str) -> ExperimentSpec:
        with self._session_factory() as session:
            if session.get(TaskRow, task_id) is None:
                raise EntityNotFoundError(f"Task {task_id} 不存在")
            if entity.parent_spec_id:
                parent = session.get(ExperimentSpecRow, entity.parent_spec_id)
                if parent is None:
                    raise EntityNotFoundError(f"父 ExperimentSpec {entity.parent_spec_id} 不存在")
                if parent.task_id != task_id:
                    raise EntityConflictError("父 ExperimentSpec 属于其他 Task")
        return super().create(
            entity, task_id=task_id, parent_spec_id=entity.parent_spec_id
        )

    def list_for_task(self, task_id: str) -> list[ExperimentSpec]:
        statement = (
            select(ExperimentSpecRow)
            .where(ExperimentSpecRow.task_id == task_id)
            .order_by(ExperimentSpecRow.created_at, ExperimentSpecRow.id)
        )
        with self._session_factory() as session:
            return [self.adapter.validate_python(row.payload) for row in session.scalars(statement)]


class ExperimentRunRepository(_CreateOnlyRepository[ExperimentRun, ExperimentRunRow]):
    row_type = ExperimentRunRow
    adapter = TypeAdapter(ExperimentRun)

    def create(self, entity: ExperimentRun) -> ExperimentRun:
        if entity.status != "running":
            raise InvalidLifecycleTransitionError("ExperimentRun 必须以 running 状态创建")
        with self._session_factory() as session:
            if session.get(ExperimentSpecRow, entity.experiment_spec_id) is None:
                raise EntityNotFoundError(
                    f"ExperimentSpec {entity.experiment_spec_id} 不存在"
                )
        return super().create(
            entity,
            experiment_spec_id=entity.experiment_spec_id,
            status=entity.status,
        )

    def update(self, run: ExperimentRun) -> ExperimentRun:
        """持久化 Run 生命周期；终态不可回退到 running。"""
        with self._session_factory.begin() as session:
            row = session.get(ExperimentRunRow, run.id)
            if row is None:
                raise EntityNotFoundError(f"ExperimentRun {run.id} 不存在")
            if row.experiment_spec_id != run.experiment_spec_id:
                raise EntityConflictError("ExperimentRun 不允许更换 ExperimentSpec")
            current = self.adapter.validate_python(row.payload)
            if current.created_at != run.created_at or current.schema_version != run.schema_version:
                raise EntityConflictError("ExperimentRun 的不可变字段发生变化")
            if row.status != "running" and run.status != row.status:
                raise InvalidLifecycleTransitionError("终态 ExperimentRun 不可再次转换状态")
            row.status = run.status
            row.payload = _payload(run)
        return run
