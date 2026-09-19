"""将 ResearchResource 解析为固定、可读取的本地原始内容。"""

from dataclasses import dataclass
from pathlib import Path

from scitrace.models import LocalLocation, ResearchResource
from scitrace.retrieval.errors import ResourceResolutionError, UnsupportedResourceError


@dataclass(frozen=True, slots=True)
class ResolvedResource:
    """一次 ingestion 使用的只读本地资源快照入口。"""

    resource_id: str
    kind: str
    path: Path


class LocalResourceResolver:
    """解析已经下载、挂载或 checkout 完成的本地资源。"""

    def resolve(self, resource: ResearchResource) -> ResolvedResource:
        if resource.kind not in {"paper", "repository"}:
            raise UnsupportedResourceError(f"V1 不索引 {resource.kind} 资源")

        for location in resource.locations:
            if isinstance(location, LocalLocation):
                path = Path(location.path).expanduser().resolve()
                if not path.exists():
                    raise ResourceResolutionError(f"本地资源不存在：{path}")
                return ResolvedResource(resource.id, resource.kind, path)
        raise ResourceResolutionError(
            f"资源 {resource.id} 没有可读取的 LocalLocation；请先 materialize 原始内容"
        )
