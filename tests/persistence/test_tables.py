"""跨数据库表类型契约测试。"""

from sqlalchemy.dialects import postgresql, sqlite

from scitrace.persistence.tables import TaskRow


def test_entity_payload_uses_jsonb_on_postgresql() -> None:
    payload_type = TaskRow.__table__.c.payload.type

    assert payload_type.dialect_impl(postgresql.dialect()).__class__.__name__ == "_PGJSONB"


def test_entity_payload_uses_json_on_sqlite() -> None:
    payload_type = TaskRow.__table__.c.payload.type

    assert payload_type.dialect_impl(sqlite.dialect()).__class__.__name__ == "_SQliteJson"


def test_task_answer_is_an_explicit_column() -> None:
    assert TaskRow.__table__.c.answer.nullable is True
