"""确定性的资源摄取与混合检索基础设施。"""

from scitrace.retrieval.chunking import DeterministicChunker
from scitrace.retrieval.embedding import FastEmbedHybridEncoder, HybridEncoder, SparseEmbedding
from scitrace.retrieval.ingestion import IngestionResult, IngestionService
from scitrace.retrieval.parsing import ResourceParser
from scitrace.retrieval.qdrant_index import QdrantHybridIndex
from scitrace.retrieval.resolving import LocalResourceResolver, ResolvedResource

__all__ = [
    "DeterministicChunker",
    "FastEmbedHybridEncoder",
    "HybridEncoder",
    "IngestionResult",
    "IngestionService",
    "LocalResourceResolver",
    "QdrantHybridIndex",
    "ResolvedResource",
    "ResourceParser",
    "SparseEmbedding",
]
