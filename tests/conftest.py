from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from scitrace.config import Settings
from scitrace.storage import Artifacts


class MemoryStore:
    """仅限测试：生产 CLI 始终使用 PostgreSQL。"""

    def __init__(self):
        self.data = {}

    def put(self, kind, value, task_id=""):
        data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        self.data[kind, data["id"]] = (deepcopy(data), task_id)
        return data["id"]

    def get(self, kind, id):
        return deepcopy(self.data[kind, id][0])

    def find(self, kind, task_id=None):
        return [
            deepcopy(data)
            for (k, _), (data, t) in self.data.items()
            if k == kind and (task_id is None or task_id == t)
        ]

    @contextmanager
    def task_lock(self, task_id):
        yield


class ScriptedModel:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = 0

    def bind_tools(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        self.calls += 1
        name, args = next(self.actions)
        return AIMessage(
            content="", tool_calls=[{"name": name, "args": args, "id": f"call-{self.calls}"}]
        )


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def basic_runtime(tmp_path, store):
    from scitrace.policy import Policy

    settings = Settings(_env_file=None, artifact_root=tmp_path)
    return SimpleNamespace(
        settings=settings,
        store=store,
        task_id="task",
        artifacts=Artifacts(tmp_path),
        policy=Policy(store, "task"),
    )
