"""ResearchResource 到 RetrievalHit 的无 LLM 最小闭环测试。"""

import pytest
from qdrant_client import QdrantClient

from scitrace.models import LocalLocation, RepositoryResource
from scitrace.retrieval import (
    DeterministicChunker,
    IngestionService,
    LocalResourceResolver,
    QdrantHybridIndex,
    ResourceParser,
)
from tests.retrieval.fakes import DeterministicHybridEncoder

pytestmark = pytest.mark.filterwarnings(
    "ignore:Payload indexes have no effect in the local Qdrant:UserWarning"
)


def build_pipeline() -> tuple[IngestionService, QdrantHybridIndex]:
    index = QdrantHybridIndex(
        QdrantClient(location=":memory:"),
        DeterministicHybridEncoder(),
        collection_name="test_resources",
    )
    service = IngestionService(
        LocalResourceResolver(),
        ResourceParser(),
        DeterministicChunker(max_chunk_tokens=30, overlap_lines=0),
        index,
    )
    return service, index


def test_repository_ingestion_and_scoped_hybrid_retrieval(tmp_path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "README.md").write_text(
        "# Evaluation\nThe target accuracy is 92.5 percent.", encoding="utf-8"
    )
    (second_dir / "README.md").write_text(
        "# Dataset\nUse the private dataset for training.", encoding="utf-8"
    )
    first = RepositoryResource(name="first", locations=[LocalLocation(path=str(first_dir))])
    second = RepositoryResource(name="second", locations=[LocalLocation(path=str(second_dir))])
    service, index = build_pipeline()

    assert service.ensure_indexed(first).chunk_count == 1
    assert service.ensure_indexed(second).chunk_count == 1
    hits = index.retrieve("target accuracy", [first.id], limit=5, prefetch_limit=5)

    assert len(hits) == 1
    assert hits[0].resource_id == first.id
    assert "92.5" in hits[0].content
    assert hits[0].locator.path == "README.md"


def test_reingestion_replaces_old_resource_points(tmp_path) -> None:
    repository_dir = tmp_path / "repo"
    repository_dir.mkdir()
    readme = repository_dir / "README.md"
    readme.write_text("old accuracy result", encoding="utf-8")
    resource = RepositoryResource(
        name="repo", locations=[LocalLocation(path=str(repository_dir))]
    )
    service, index = build_pipeline()
    service.ensure_indexed(resource)

    readme.write_text("new dataset result", encoding="utf-8")
    service.ensure_indexed(resource)

    hits = index.retrieve("dataset", [resource.id], limit=5, prefetch_limit=5)
    assert len(hits) == 1
    assert hits[0].content == "new dataset result"
