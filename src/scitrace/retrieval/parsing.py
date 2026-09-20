"""PyMuPDF4LLM Paper parser 与确定性 Repository reader。"""

import mimetypes
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from scitrace.models import ArtifactReference, ContentLocator, FileLocator, PaperLocator
from scitrace.persistence.artifacts import ArtifactStore
from scitrace.retrieval.errors import UnsupportedResourceError
from scitrace.retrieval.resolving import ResolvedResource

SUPPORTED_TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".css", ".go", ".h", ".hpp", ".html", ".ini",
    ".java", ".js", ".json", ".md", ".py", ".rst", ".sh", ".toml", ".ts",
    ".tsx", ".txt", ".yaml", ".yml",
} # 文件白名单
IGNORED_DIRECTORY_NAMES = {".git", ".venv", "__pycache__", "node_modules", "dist"}
IMAGE_PAGE_PATTERN = re.compile(r"-p(\d+)-", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedUnit:
    """带原文位置和相关 Artifact 的天然解析单元。"""

    content: str
    locator: ContentLocator
    artifacts: tuple[ArtifactReference, ...] = field(default_factory=tuple)


class ResourceParser:
    """将第三方/本地 reader 输出适配为稳定的 ParsedUnit contract。"""

    def __init__(
        self,
        artifact_store: ArtifactStore | None = None,
        *,
        paper_to_markdown: Callable[..., Any] | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self._paper_to_markdown = paper_to_markdown

    def parse(self, resource: ResolvedResource) -> list[ParsedUnit]:
        if resource.kind == "paper":
            return self._parse_paper(resource)
        if resource.kind == "repository":
            return self._parse_repository(resource.path)
        raise UnsupportedResourceError(f"不支持解析 {resource.kind}")

    def _parse_paper(self, resource: ResolvedResource) -> list[ParsedUnit]:
        path = resource.path
        if path.suffix.lower() != ".pdf": # 当前版本暂时只支持 PDF
            raise UnsupportedResourceError("PaperResource V1 仅支持本地 PDF")
        if self.artifact_store is None:
            raise ValueError("Paper parser 必须配置 ArtifactStore 才能保存 Figure")

        with tempfile.TemporaryDirectory(prefix="scitrace-pdf-") as temporary:
            image_directory = Path(temporary)
            pages = self._get_paper_backend()(
                str(path),
                page_chunks=True,
                write_images=True,
                image_path=str(image_directory),
                image_format="png",
                force_text=True,
                show_progress=False,
            )
            if not isinstance(pages, list):
                raise RuntimeError("PyMuPDF4LLM page_chunks 未返回分页结果")
            artifacts_by_page, path_replacements = self._persist_images(
                resource.resource_id, image_directory
            )
            units: list[ParsedUnit] = []
            for fallback_page, page in enumerate(pages, start=1):
                metadata = page.get("metadata", {})
                page_number = int(metadata.get("page_number", fallback_page))
                content = str(page.get("text", ""))
                for original, artifact_uri in path_replacements.items():
                    content = content.replace(f"]({original})", f"]({artifact_uri})")
                if content.strip():
                    units.append(
                        ParsedUnit(
                            content=content,
                            locator=PaperLocator(start_page=page_number),
                            artifacts=tuple(artifacts_by_page.get(page_number, [])),
                        )
                    )
            return units

    def _get_paper_backend(self) -> Callable[..., Any]:
        """延迟加载重依赖，避免 Repository/Qdrant 路径产生 PDF import 副作用。"""
        if self._paper_to_markdown is None:
            import pymupdf4llm

            self._paper_to_markdown = pymupdf4llm.to_markdown
        return self._paper_to_markdown

    def _persist_images(
        self, resource_id: str, image_directory: Path
    ) -> tuple[dict[int, list[ArtifactReference]], dict[str, str]]:
        by_page: dict[int, list[ArtifactReference]] = {}
        replacements: dict[str, str] = {}
        assert self.artifact_store is not None
        for image in sorted(path for path in image_directory.iterdir() if path.is_file()):
            match = IMAGE_PAGE_PATTERN.search(image.name)
            if match is None:
                continue
            page_number = int(match.group(1))
            artifact = self.artifact_store.put_bytes(
                namespace=f"resources/{resource_id}/figures",
                name=image.name,
                content=image.read_bytes(),
                media_type=mimetypes.guess_type(image.name)[0] or "application/octet-stream",
            )
            by_page.setdefault(page_number, []).append(artifact)
            replacements[str(image)] = artifact.uri
            replacements[image.as_posix()] = artifact.uri
            replacements[image.name] = artifact.uri
        return by_page, replacements

    def _parse_repository(self, path: Path) -> list[ParsedUnit]:
        root = path if path.is_dir() else path.parent # 兼容一个小文件以及一整个仓库
        candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file()) # 得到一个装有所有文件的列表
        units: list[ParsedUnit] = []
        for file_path in candidates:
            if any(part in IGNORED_DIRECTORY_NAMES for part in file_path.relative_to(root).parts):
                continue
            if file_path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
                continue
            try:
                # 不能 strip：前导/尾随空行也是原文件行号的一部分，删除后会让
                # FileLocator 与真实文件位置错位。newline="" 还会保留原始换行符。
                with file_path.open("r", encoding="utf-8", newline="") as source:
                    content = source.read()
            except UnicodeDecodeError:
                continue
            if content.strip():
                relative_path = file_path.relative_to(root).as_posix()
                line_count = len(content.splitlines())
                units.append(
                    ParsedUnit(
                        content,
                        FileLocator(path=relative_path, start_line=1, end_line=line_count),
                    )
                )
        return units
