"""Resolve → Parse → Chunk → Encode/Index 的同步编排。"""

from dataclasses import dataclass

from scitrace.models import ResearchResource
from scitrace.retrieval.chunking import DeterministicChunker
from scitrace.retrieval.parsing import ResourceParser
from scitrace.retrieval.qdrant_index import QdrantHybridIndex
from scitrace.retrieval.resolving import LocalResourceResolver


@dataclass(frozen=True, slots=True)
class IngestionResult:
    resource_id: str
    chunk_count: int


class IngestionService:
    """外层 Application/Wrapper 调用的确定性 Ingestion 服务。"""

    def __init__(
        self,
        resolver: LocalResourceResolver,
        parser: ResourceParser,
        chunker: DeterministicChunker,
        index: QdrantHybridIndex,
    ) -> None:
        self.resolver = resolver
        self.parser = parser
        self.chunker = chunker
        self.index = index

    def ensure_indexed(self, resource: ResearchResource) -> IngestionResult:
        resolved = self.resolver.resolve(resource)
        units = self.parser.parse(resolved)
        chunks = self.chunker.chunk(resource.id, units)
        self.index.replace_resource(resource.id, chunks)
        return IngestionResult(resource_id=resource.id, chunk_count=len(chunks))
