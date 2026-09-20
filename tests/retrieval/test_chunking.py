"""解析和分块契约测试。"""

from scitrace.models import FileLocator
from scitrace.retrieval import DeterministicChunker
from scitrace.retrieval.parsing import ParsedUnit


def test_short_natural_unit_is_not_split() -> None:
    unit = ParsedUnit("alpha beta", FileLocator(path="README.md", start_line=1, end_line=1))

    chunks = DeterministicChunker(max_chunk_tokens=10).chunk("resource-1", [unit])

    assert len(chunks) == 1
    assert chunks[0].locator == unit.locator


def test_long_file_unit_preserves_line_ranges() -> None:
    unit = ParsedUnit(
        "alpha beta\ngamma delta\nepsilon zeta",
        FileLocator(path="train.py", start_line=10, end_line=12),
    )

    chunks = DeterministicChunker(max_chunk_tokens=2, overlap_lines=0).chunk(
        "resource-1", [unit]
    )

    assert [chunk.locator.start_line for chunk in chunks] == [10, 11, 12]
    assert [chunk.locator.end_line for chunk in chunks] == [10, 11, 12]


def test_chunk_content_keeps_blank_lines_in_locator_range() -> None:
    unit = ParsedUnit(
        "\nalpha beta\n\ngamma delta\n",
        FileLocator(path="train.py", start_line=1, end_line=4),
    )

    chunks = DeterministicChunker(max_chunk_tokens=2, overlap_lines=0).chunk(
        "resource-1", [unit]
    )

    assert chunks[0].content == "\nalpha beta\n\n"
    assert chunks[0].locator.start_line == 1
    assert chunks[0].locator.end_line == 3
    assert chunks[1].content == "gamma delta\n"
    assert chunks[1].locator.start_line == 4
    assert chunks[1].locator.end_line == 4
