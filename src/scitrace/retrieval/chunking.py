"""LangChain splitter 与 SciTrace provenance 之间的薄适配层。"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from scitrace.models import ArtifactReference, FileLocator, PaperLocator, ResourceChunk
from scitrace.retrieval.parsing import ParsedUnit


class ResourceChunker:
    """只对过长天然单元切分，并把字符位置适配回 ContentLocator。"""

    def __init__(self, *, chunk_size: int = 1600, chunk_overlap: int | None = None) -> None:
        if chunk_overlap is None:
            chunk_overlap = min(160, chunk_size // 10)
        if chunk_size < 1 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_size 必须为正，chunk_overlap 必须满足 0 <= overlap < size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
            keep_separator=True,
            strip_whitespace=False,
            separators=["\n# ", "\n## ", "\n### ", "\n\n", "\n", " ", ""],
        )

    def chunk(self, resource_id: str, units: list[ParsedUnit]) -> list[ResourceChunk]:
        chunks: list[ResourceChunk] = []
        for unit in units:
            chunks.extend(self._chunk_unit(resource_id, unit))
        return chunks

    def _chunk_unit(self, resource_id: str, unit: ParsedUnit) -> list[ResourceChunk]:
        if len(unit.content) <= self.chunk_size:
            return [
                ResourceChunk(
                    resource_id=resource_id,
                    content=unit.content,
                    locator=unit.locator,
                    artifacts=list(unit.artifacts),
                )
            ]

        documents = self._splitter.create_documents([unit.content])
        chunks: list[ResourceChunk] = []
        for document in documents:
            if not document.page_content.strip():
                continue
            start = int(document.metadata["start_index"])
            end = start + len(document.page_content)
            chunks.append(
                ResourceChunk(
                    resource_id=resource_id,
                    content=document.page_content,
                    locator=self._slice_locator(unit, start, end),
                    artifacts=self._referenced_artifacts(document.page_content, unit.artifacts),
                )
            )
        return chunks

    @staticmethod
    def _slice_locator(unit: ParsedUnit, start: int, end: int):
        if isinstance(unit.locator, FileLocator):
            base_line = unit.locator.start_line or 1
            start_line = base_line + unit.content.count("\n", 0, start)
            last_character = max(start, end - 1)
            end_line = base_line + unit.content.count("\n", 0, last_character)
            return FileLocator(
                path=unit.locator.path,
                start_line=start_line,
                end_line=end_line,
            )
        locator = unit.locator
        assert isinstance(locator, PaperLocator)
        return locator

    @staticmethod
    def _referenced_artifacts(
        content: str, artifacts: tuple[ArtifactReference, ...]
    ) -> list[ArtifactReference]:
        return [artifact for artifact in artifacts if artifact.uri in content]


# 保留旧名称一个版本，避免现有 application wiring 立即失效。
DeterministicChunker = ResourceChunker
