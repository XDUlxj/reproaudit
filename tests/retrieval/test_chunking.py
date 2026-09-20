"""解析和分块契约测试。"""

from scitrace.models import ArtifactReference, FileLocator, PaperLocator
from scitrace.retrieval import ResourceChunker
from scitrace.retrieval.parsing import ParsedUnit


def test_short_natural_unit_is_not_split() -> None:
    unit = ParsedUnit("alpha beta", FileLocator(path="README.md", start_line=1, end_line=1))

    chunks = ResourceChunker(chunk_size=100).chunk("resource-1", [unit])

    assert len(chunks) == 1
    assert chunks[0].locator == unit.locator


def test_long_file_unit_preserves_line_ranges() -> None:
    unit = ParsedUnit(
        "alpha beta\ngamma delta\nepsilon zeta",
        FileLocator(path="train.py", start_line=10, end_line=12),
    )

    chunks = ResourceChunker(chunk_size=11, chunk_overlap=0).chunk(
        "resource-1", [unit]
    )

    assert len(chunks) >= 2
    assert chunks[0].locator.start_line == 10
    assert chunks[-1].locator.end_line == 12


def test_chunk_content_keeps_blank_lines_in_locator_range() -> None:
    unit = ParsedUnit(
        "\nalpha beta\n\ngamma delta\n",
        FileLocator(path="train.py", start_line=1, end_line=4),
    )

    chunks = ResourceChunker(chunk_size=12, chunk_overlap=0).chunk(
        "resource-1", [unit]
    )

    assert chunks[0].content == "\nalpha beta"
    assert chunks[0].locator.start_line == 1
    assert chunks[0].locator.end_line == 2
    assert chunks[-1].content == "\ngamma delta"
    assert chunks[-1].locator.start_line == 3
    assert chunks[-1].locator.end_line == 4


def test_paper_chunk_only_carries_artifact_referenced_by_markdown() -> None:
    first = ArtifactReference(
        name="first.png", uri="artifact://figures/first.png", sha256="a" * 64,
        media_type="image/png",
    )
    second = ArtifactReference(
        name="second.png", uri="artifact://figures/second.png", sha256="b" * 64,
        media_type="image/png",
    )
    unit = ParsedUnit(
        "# Figure\n![](artifact://figures/first.png)\n" + "detail " * 20,
        PaperLocator(start_page=3),
        artifacts=(first, second),
    )

    chunks = ResourceChunker(chunk_size=70, chunk_overlap=5).chunk("paper-1", [unit])

    figure_chunks = [chunk for chunk in chunks if first.uri in chunk.content]
    assert figure_chunks
    assert figure_chunks[0].artifacts == [first]
    assert all(second not in chunk.artifacts for chunk in chunks)
