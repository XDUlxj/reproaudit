"""Qdrant 检索输入边界测试。"""

import pytest
from qdrant_client import QdrantClient

from scitrace.models import ArtifactReference, FileLocator, ResourceChunk
from scitrace.retrieval import QdrantHybridIndex
from scitrace.retrieval.errors import InvalidRetrievalRequestError
from tests.retrieval.fakes import DeterministicHybridEncoder


def test_retrieve_requires_resource_scope() -> None:
    index = QdrantHybridIndex(QdrantClient(location=":memory:"), DeterministicHybridEncoder())

    with pytest.raises(InvalidRetrievalRequestError):
        index.retrieve("accuracy", [])


def test_artifact_reference_round_trips_through_qdrant_payload() -> None:
    index = QdrantHybridIndex(QdrantClient(location=":memory:"), DeterministicHybridEncoder())
    artifact = ArtifactReference(
        name="figure.png",
        uri="artifact://resources/paper-1/figures/figure.png",
        sha256="a" * 64,
        media_type="image/png",
    )
    index.replace_resource(
        "paper-1",
        [
            ResourceChunk(
                resource_id="paper-1",
                content=f"Figure 1 accuracy results ![]({artifact.uri})",
                locator=FileLocator(path="paper.md", start_line=1, end_line=1),
                artifacts=[artifact],
            )
        ],
    )

    hits = index.retrieve("accuracy", ["paper-1"], limit=1, prefetch_limit=2)

    assert hits[0].artifacts == [artifact]
