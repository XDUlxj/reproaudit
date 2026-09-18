from scitrace.models.task import Task


def test_task_is_versioned_record_with_stable_defaults():
    """任务创建集中在模型中，后续新增字段不会隐式丢失。"""
    task = Task(id="task-1", query="只分析论文")

    assert task.schema_version == 1
    assert task.status == "created"
    assert task.local_inputs == []
    assert task.trusted_project_urls == []
    assert task.requires_execution is False
    assert task.model_dump(mode="json")["id"] == "task-1"
