"""业务记录与文件分离；数据库只存结构化对象和证据引用。"""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from scitrace.models.core import Record

MIGRATION = """
CREATE SCHEMA IF NOT EXISTS scitrace;
CREATE TABLE IF NOT EXISTS scitrace.migrations(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS scitrace.records (
  kind TEXT NOT NULL, id TEXT NOT NULL, task_id TEXT NOT NULL DEFAULT '',
  payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(kind, id)
);
CREATE INDEX IF NOT EXISTS records_task_idx ON scitrace.records(task_id, kind);
INSERT INTO scitrace.migrations(version) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS scitrace.record_tasks (
  kind TEXT NOT NULL, record_id TEXT NOT NULL, task_id TEXT NOT NULL,
  PRIMARY KEY(kind,record_id,task_id)
);
INSERT INTO scitrace.record_tasks(kind,record_id,task_id)
SELECT kind,id,task_id FROM scitrace.records WHERE task_id <> '' ON CONFLICT DO NOTHING;
INSERT INTO scitrace.migrations(version) VALUES (2) ON CONFLICT DO NOTHING;
CREATE SCHEMA IF NOT EXISTS scitrace_checkpoints;
"""


class Store:
    def __init__(self, dsn: str):
        self.conn = psycopg.connect(dsn, autocommit=True, connect_timeout=10)

    def migrate(self):
        self.conn.execute(MIGRATION)

    def close(self):
        self.conn.close()

    def put(self, kind: str, value: Record | dict, task_id: str = "") -> str:
        data = value.model_dump(mode="json") if isinstance(value, Record) else dict(value)
        data.setdefault("schema_version", 1)
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO scitrace.records(kind,id,task_id,payload) VALUES(%s,%s,%s,%s) "
                "ON CONFLICT(kind,id) DO UPDATE SET payload=EXCLUDED.payload, "
                "task_id=EXCLUDED.task_id, updated_at=now()",
                (kind, data["id"], task_id, Jsonb(data)),
            )
            if task_id:
                self.conn.execute(
                    "INSERT INTO scitrace.record_tasks(kind,record_id,task_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                    (kind, data["id"], task_id),
                )
        return data["id"]

    def get(self, kind: str, id: str) -> dict:
        row = self.conn.execute(
            "SELECT payload FROM scitrace.records WHERE kind=%s AND id=%s", (kind, id)
        ).fetchone()
        if not row:
            raise KeyError(f"找不到 {kind}: {id}")
        return row[0]

    def find(self, kind: str, task_id: str | None = None) -> list[dict]:
        if task_id is None:
            rows = self.conn.execute(
                "SELECT payload FROM scitrace.records WHERE kind=%s ORDER BY updated_at", (kind,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT r.payload FROM scitrace.records r JOIN scitrace.record_tasks t "
                "ON r.kind=t.kind AND r.id=t.record_id WHERE r.kind=%s AND t.task_id=%s ORDER BY r.updated_at",
                (kind, task_id),
            ).fetchall()
        return [r[0] for r in rows]

    @contextmanager
    def task_lock(self, task_id: str):
        # 同一任务禁止两个 CLI 同时恢复，避免外部副作用重复提交。
        acquired = self.conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (task_id,)
        ).fetchone()[0]
        if not acquired:
            raise RuntimeError("该任务正在另一个进程中运行")
        try:
            yield
        finally:
            self.conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (task_id,))


class Artifacts:
    """产物文件管理器"""
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, ref: str) -> Path:
        """转成真实路径，并且防止路径穿越"""
        path = (self.root / ref).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("产物路径越界")
        return path

    def write(self, ref: str, data: bytes) -> str:
        """文件写入"""
        path = self.path(ref) # 得到真实路径
        path.parent.mkdir(parents=True, exist_ok=True) # 创建文件夹
        tmp = path.with_name(path.name + "." + str(uuid4()) + ".tmp") # 写入临时文件，原子写入
        tmp.write_bytes(data) 
        os.replace(tmp, path)
        return ref

    def json(self, ref: str, value) -> str:
        """序列化写入"""
        return self.write(ref, json.dumps(value, ensure_ascii=False, indent=2).encode())
