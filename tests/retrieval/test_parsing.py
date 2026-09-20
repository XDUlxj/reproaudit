"""资源解析、图片持久化和 provenance 回归测试。"""

from pathlib import Path

from scitrace.persistence import LocalArtifactStore
from scitrace.retrieval.parsing import ResourceParser
from scitrace.retrieval.resolving import ResolvedResource


def test_repository_parser_preserves_leading_and_trailing_blank_lines(tmp_path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "example.py"
    original = "\r\n\r\nvalue = 1\r\n\r\n"
    with source.open("w", encoding="utf-8", newline="") as output:
        output.write(original)

    units = ResourceParser().parse(ResolvedResource("resource-1", "repository", repository))

    assert len(units) == 1
    assert units[0].content == original
    assert units[0].locator.path == "example.py"
    assert units[0].locator.start_line == 1
    assert units[0].locator.end_line == 4


def test_paper_parser_adapts_page_markdown_and_persists_images(tmp_path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"fake-pdf-for-adapter-test")
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")

    def fake_to_markdown(_path: str, **options):
        image_path = Path(options["image_path"])
        # PyMuPDF4LLM 当前格式：{filename}-{pagenumber}-{image_number}.png。
        # Parser 不应通过解析该名称判断图片属于哪一页。
        image = image_path / "paper.pdf-0-0.png"
        image.write_bytes(b"png-content")
        return [
            {
                "metadata": {"page_number": 1},
                "text": f"# Results\n\n| metric | value |\n|---|---|\n| acc | 92.5 |\n\n![]({image})",
            }
        ]

    units = ResourceParser(artifact_store, paper_to_markdown=fake_to_markdown).parse(
        ResolvedResource("paper-1", "paper", pdf)
    )

    assert len(units) == 1
    assert "| acc | 92.5 |" in units[0].content
    assert units[0].locator.start_page == 1
    assert len(units[0].artifacts) == 1
    artifact = units[0].artifacts[0]
    assert artifact.uri in units[0].content
    assert artifact_store.resolve(artifact).read_bytes() == b"png-content"


def test_paper_parser_assigns_images_from_page_markdown_not_filename(tmp_path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"fake-pdf")
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")

    def fake_to_markdown(_path: str, **options):
        image_path = Path(options["image_path"])
        oddly_named = image_path / "backend-name-without-page-marker.png"
        oddly_named.write_bytes(b"image")
        return [
            {"metadata": {"page_number": 7}, "text": f"Figure caption\n![]({oddly_named})"}
        ]

    units = ResourceParser(artifact_store, paper_to_markdown=fake_to_markdown).parse(
        ResolvedResource("paper-1", "paper", pdf)
    )

    assert units[0].locator.start_page == 7
    assert len(units[0].artifacts) == 1
    assert units[0].artifacts[0].uri in units[0].content
