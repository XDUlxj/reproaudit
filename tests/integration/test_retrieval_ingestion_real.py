"""真实 PDF → Ingestion → Qdrant → Retrieval 端到端集成测试。"""

import os
import uuid
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from scitrace.models import LocalLocation, PaperLocator, PaperResource
from scitrace.persistence import LocalArtifactStore
from scitrace.retrieval import (
    FastEmbedHybridEncoder,
    IngestionService,
    LocalResourceResolver,
    QdrantHybridIndex,
    ResourceChunker,
    ResourceParser,
)

pytestmark = pytest.mark.integration

PAPER_PATH = (
    Path(__file__).parents[1]
    / "Stoica 等 - 2024 - ZIPIT! MERGING MODELS FROM DIFFERENT TASKS.pdf"
)


def test_real_paper_ingestion_and_scoped_hybrid_retrieval(tmp_path) -> None:
    """完整验证 ResearchResource → ensure_indexed → Qdrant → retrieve。"""
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    if not qdrant_url or not qdrant_api_key:
        pytest.skip("需要通过环境变量提供 QDRANT_URL 和 QDRANT_API_KEY")
    if not PAPER_PATH.is_file():
        pytest.skip(f"真实测试论文不存在：{PAPER_PATH}")

    collection_name = f"scitrace_v2_integration_{uuid.uuid4().hex}"
    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key, timeout=60)
    index = QdrantHybridIndex(
        client,
        FastEmbedHybridEncoder(),
        collection_name=collection_name,
    )
    ingestion = IngestionService(
        LocalResourceResolver(),
        ResourceParser(LocalArtifactStore(tmp_path / "artifacts")),
        ResourceChunker(chunk_size=1600, chunk_overlap=160),
        index,
    )
    resource = PaperResource(
        name="ZIPIT! Merging Models from Different Tasks",
        locations=[LocalLocation(path=str(PAPER_PATH))],
    )

    try:
        result = ingestion.ensure_indexed(resource)
        hits = index.retrieve(
            "How does ZipIt merge models trained on different tasks without additional training?",
            [resource.id],
            limit=5,
            prefetch_limit=20,
        )

        assert result.resource_id == resource.id
        assert result.chunk_count > 20
        assert hits
        assert all(hit.resource_id == resource.id for hit in hits)
        assert all(isinstance(hit.locator, PaperLocator) for hit in hits)
        assert all(hit.content.strip() for hit in hits)
        assert any(
            term in " ".join(hit.content.lower() for hit in hits)
            for term in ("zipit", "merge", "merging")
        )
    finally:
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name)

    assert not client.collection_exists(collection_name)
