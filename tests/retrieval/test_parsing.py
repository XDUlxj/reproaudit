"""资源解析的 provenance 回归测试。"""

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
