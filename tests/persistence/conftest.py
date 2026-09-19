"""Persistence 测试夹具。"""

from collections.abc import Iterator

import pytest

from scitrace.persistence import DatabaseRuntime, create_database_runtime, initialize_schema


@pytest.fixture
def database() -> Iterator[DatabaseRuntime]:
    runtime = create_database_runtime("sqlite+pysqlite:///:memory:")
    initialize_schema(runtime)
    try:
        yield runtime
    finally:
        runtime.engine.dispose()
