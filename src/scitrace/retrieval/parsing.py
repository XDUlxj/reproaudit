"""不涉及 LLM 的论文与仓库文本提取。"""

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from scitrace.models import ContentLocator, FileLocator, PaperLocator
from scitrace.retrieval.errors import UnsupportedResourceError
from scitrace.retrieval.resolving import ResolvedResource

SUPPORTED_TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".css", ".go", ".h", ".hpp", ".html", ".ini",
    ".java", ".js", ".json", ".md", ".py", ".rst", ".sh", ".toml", ".ts",
    ".tsx", ".txt", ".yaml", ".yml",
}
IGNORED_DIRECTORY_NAMES = {".git", ".venv", "__pycache__", "node_modules", "dist"}


@dataclass(frozen=True, slots=True)
class ParsedUnit:
    """带原文位置的天然解析单元。"""

    content: str
    locator: ContentLocator


class ResourceParser:
    """按资源类型执行确定性内容提取。"""

    def parse(self, resource: ResolvedResource) -> list[ParsedUnit]:
        if resource.kind == "paper":
            return self._parse_paper(resource.path)
        if resource.kind == "repository":
            return self._parse_repository(resource.path)
        raise UnsupportedResourceError(f"不支持解析 {resource.kind}")

    def _parse_paper(self, path: Path) -> list[ParsedUnit]:
        if path.suffix.lower() != ".pdf":
            raise UnsupportedResourceError("PaperResource V1 仅支持本地 PDF")
        units: list[ParsedUnit] = []
        for page_number, page in enumerate(PdfReader(path).pages, start=1):
            content = (page.extract_text() or "").strip()
            if content:
                units.append(ParsedUnit(content, PaperLocator(start_page=page_number)))
        return units

    def _parse_repository(self, path: Path) -> list[ParsedUnit]:
        root = path if path.is_dir() else path.parent
        candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
        units: list[ParsedUnit] = []
        for file_path in candidates:
            if any(part in IGNORED_DIRECTORY_NAMES for part in file_path.relative_to(root).parts):
                continue
            if file_path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
                continue
            try:
                content = file_path.read_text(encoding="utf-8").strip()
            except UnicodeDecodeError:
                continue
            if content:
                relative_path = file_path.relative_to(root).as_posix()
                line_count = len(content.splitlines())
                units.append(
                    ParsedUnit(
                        content,
                        FileLocator(path=relative_path, start_line=1, end_line=line_count),
                    )
                )
        return units
