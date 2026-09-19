"""四类 Entity 的 SQLite 持久化契约测试。"""

from datetime import UTC, datetime

import pytest

from scitrace.models import (
    ExperimentRun,
    ExperimentSpec,
    PaperResource,
    Task,
    WebLocation,
)
from scitrace.persistence import (
    EntityConflictError,
    EntityNotFoundError,
    ExperimentRunRepository,
    ExperimentSpecRepository,
    InvalidLifecycleTransitionError,
    ResourceRepository,
    TaskRepository,
)
from scitrace.persistence.database import DatabaseRuntime


def test_persists_task_and_replay_is_idempotent(database: DatabaseRuntime) -> None:
    repository = TaskRepository(database.session_factory)
    task = Task(query="复现论文 X")

    assert repository.create(task) == task
    assert repository.create(task) == task
    assert repository.require(task.id) == task


def test_rejects_same_id_with_different_content(database: DatabaseRuntime) -> None:
    repository = TaskRepository(database.session_factory)
    task = Task(query="原任务")
    repository.create(task)

    changed = task.model_copy(update={"query": "不同任务"})
    with pytest.raises(EntityConflictError):
        repository.create(changed)


def test_updates_task_lifecycle(database: DatabaseRuntime) -> None:
    repository = TaskRepository(database.session_factory)
    created = repository.create(Task(query="复现论文 X"))
    running = created.model_copy(update={"status": "running"})

    repository.update(running)

    assert repository.require(created.id).status == "running"


def test_terminal_task_cannot_return_to_running(database: DatabaseRuntime) -> None:
    repository = TaskRepository(database.session_factory)
    created = repository.create(Task(query="复现论文 X"))
    finished = created.model_copy(update={"status": "finished", "answer": "完成"})
    repository.update(created.model_copy(update={"status": "running"}))
    repository.update(finished)

    with pytest.raises(InvalidLifecycleTransitionError):
        repository.update(created.model_copy(update={"status": "running"}))


def test_persists_and_attaches_resource(database: DatabaseRuntime) -> None:
    tasks = TaskRepository(database.session_factory)
    resources = ResourceRepository(database.session_factory)
    task = tasks.create(Task(query="复现论文 X"))
    resource = resources.create(
        PaperResource(name="Paper X", locations=[WebLocation(url="https://example.org/x")])
    )

    resources.attach_to_task(task.id, resource.id)
    resources.attach_to_task(task.id, resource.id)

    assert resources.list_for_task(task.id) == [resource]


def test_spec_requires_existing_task_and_parent(database: DatabaseRuntime) -> None:
    specs = ExperimentSpecRepository(database.session_factory)
    spec = ExperimentSpec(goal="复现结果", commands=["python train.py"])

    with pytest.raises(EntityNotFoundError):
        specs.create(spec, task_id="missing-task")


def test_same_spec_id_cannot_be_reused_by_another_task(database: DatabaseRuntime) -> None:
    tasks = TaskRepository(database.session_factory)
    specs = ExperimentSpecRepository(database.session_factory)
    first_task = tasks.create(Task(query="任务一"))
    second_task = tasks.create(Task(query="任务二"))
    spec = specs.create(
        ExperimentSpec(goal="复现结果", commands=["python train.py"]),
        task_id=first_task.id,
    )

    with pytest.raises(EntityConflictError):
        specs.create(spec, task_id=second_task.id)


def test_persists_spec_revision_and_run_lifecycle(database: DatabaseRuntime) -> None:
    tasks = TaskRepository(database.session_factory)
    specs = ExperimentSpecRepository(database.session_factory)
    runs = ExperimentRunRepository(database.session_factory)
    task = tasks.create(Task(query="复现论文 X"))
    first = specs.create(
        ExperimentSpec(goal="复现结果", commands=["python train.py"]), task_id=task.id
    )
    revised = specs.create(
        ExperimentSpec(
            goal="复现结果",
            commands=["python train.py --batch-size 32"],
            parent_spec_id=first.id,
        ),
        task_id=task.id,
    )
    running = runs.create(ExperimentRun(experiment_spec_id=revised.id))
    succeeded = running.model_copy(
        update={"status": "succeeded", "finished_at": datetime.now(UTC)}
    )

    runs.update(succeeded)

    assert specs.list_for_task(task.id) == [first, revised]
    assert runs.require(running.id).status == "succeeded"

    with pytest.raises(InvalidLifecycleTransitionError):
        runs.update(running)
