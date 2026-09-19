"""Qdrant 检索输入边界测试。"""

import pytest
from qdrant_client import QdrantClient

from scitrace.retrieval import QdrantHybridIndex
from scitrace.retrieval.errors import InvalidRetrievalRequestError
from tests.retrieval.fakes import DeterministicHybridEncoder


def test_retrieve_requires_resource_scope() -> None:
    index = QdrantHybridIndex(QdrantClient(location=":memory:"), DeterministicHybridEncoder())

    with pytest.raises(InvalidRetrievalRequestError):
        index.retrieve("accuracy", [])
