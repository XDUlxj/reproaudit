"""保留原文行/页定位的确定性分块。"""

import re

from scitrace.models import FileLocator, PaperLocator, ResourceChunk
from scitrace.retrieval.parsing import ParsedUnit

TOKEN_PATTERN = re.compile(r"[\w]+|[^\w\s]", re.UNICODE)


class DeterministicChunker:
    """天然单元过长时才按行切分，并保留少量行重叠。"""

    def __init__(self, *, max_chunk_tokens: int = 400, overlap_lines: int = 2) -> None:
        if max_chunk_tokens < 1 or overlap_lines < 0:
            raise ValueError("分块参数必须为正数，overlap_lines 可为 0")
        self.max_chunk_tokens = max_chunk_tokens
        self.overlap_lines = overlap_lines

    def chunk(self, resource_id: str, units: list[ParsedUnit]) -> list[ResourceChunk]:
        chunks: list[ResourceChunk] = []
        for unit in units:
            chunks.extend(self._chunk_unit(resource_id, unit))
        return chunks

    def _chunk_unit(self, resource_id: str, unit: ParsedUnit) -> list[ResourceChunk]:
        lines = unit.content.splitlines()
        if self._token_count(unit.content) <= self.max_chunk_tokens:
            return [ResourceChunk(resource_id=resource_id, content=unit.content, locator=unit.locator)]

        result: list[ResourceChunk] = []
        start = 0
        while start < len(lines):
            end = start
            token_count = 0
            while end < len(lines):
                next_count = self._token_count(lines[end])
                if end > start and token_count + next_count > self.max_chunk_tokens:
                    break
                token_count += next_count
                end += 1
            if end == start:
                end += 1
            content = "\n".join(lines[start:end]).strip()
            if content:
                result.append(
                    ResourceChunk(
                        resource_id=resource_id,
                        content=content,
                        locator=self._slice_locator(unit, start, end),
                    )
                )
            if end >= len(lines):
                break
            start = max(start + 1, end - self.overlap_lines)
        return result

    @staticmethod
    def _token_count(text: str) -> int:
        return len(TOKEN_PATTERN.findall(text))

    @staticmethod
    def _slice_locator(unit: ParsedUnit, start: int, end: int):
        if isinstance(unit.locator, FileLocator):
            base = unit.locator.start_line or 1
            return FileLocator(
                path=unit.locator.path,
                start_line=base + start,
                end_line=base + end - 1,
            )
        locator = unit.locator
        assert isinstance(locator, PaperLocator)
        return locator
