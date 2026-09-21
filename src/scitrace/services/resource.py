"""科研资源强身份匹配服务。"""

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from scitrace.models import ResearchResource
from scitrace.models.discovery import CandidateBase, DeduplicationResult, ResourceCandidate


def _normalized_text(value: Any) -> str | None:
    """统一字符串。"""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def _normalized_doi(value: Any) -> str | None:
    """规范 DOI。"""
    normalized = _normalized_text(value)
    if normalized is None:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix)
    return normalized.strip() or None


def _repository_identity(candidate: dict[str, Any]) -> tuple[str, str, str] | None:
    """提取仓库身份。"""
    provider = _normalized_text(candidate.get("provider"))
    owner = _normalized_text(candidate.get("owner"))
    name = _normalized_text(candidate.get("repository") or candidate.get("name"))
    raw_url = candidate.get("canonical_url") or candidate.get("url")
    if isinstance(raw_url, str) and raw_url.strip():
        parsed = urlparse(raw_url.removesuffix(".git"))
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.hostname and len(parts) >= 2:
            provider = parsed.hostname.lower().removeprefix("www.")
            owner, name = parts[0].lower(), parts[1].lower()
    if provider and owner and name:
        return provider, owner, name
    return None


def _resource_candidate(resource: ResearchResource) -> dict[str, Any]:
    """将 ResearchResource 转为 Candidate，供强身份匹配使用。"""
    candidate = resource.model_dump(mode="json")
    candidate.update(resource.metadata)
    if resource.kind == "repository" and resource.locations:
        location = resource.locations[0]
        if location.kind == "web":
            candidate["url"] = location.url
    return candidate


def _canonical_identity(
    candidate: ResourceCandidate | ResearchResource,
) -> tuple[str, str] | None:
    """提取规范身份的类型和值；身份不足时返回 ``None``。"""
    value = (
        candidate.model_dump(mode="json")
        if isinstance(candidate, CandidateBase)
        else _resource_candidate(candidate)
    )
    kind = value.get("kind")
    if kind == "paper":
        doi = _normalized_doi(value.get("doi"))
        if doi:
            return "doi", doi
        arxiv_id = _normalized_text(value.get("arxiv_id"))
        if arxiv_id:
            return "arxiv", arxiv_id
    elif kind == "repository":
        identity = _repository_identity(value)
        if identity:
            return "repository", ":".join(identity)
    elif kind == "dataset":
        parts = (
            _normalized_text(value.get("provider")),
            _normalized_text(value.get("dataset_id")),
            _normalized_text(value.get("version")),
        )
        if all(parts):
            return "dataset", ":".join(part for part in parts if part)
    elif kind == "model":
        parts = (
            _normalized_text(value.get("provider")),
            _normalized_text(value.get("model_id")),
            _normalized_text(value.get("revision")),
        )
        if all(parts):
            return "model", ":".join(part for part in parts if part)
    return None


class ResourceService:
    """以强身份标识保证 Resource 去重；可由持久化适配器提供全局已知资源。"""

    def __init__(self, resources: Iterable[ResearchResource] = ()) -> None:
        self._resources = {resource.id: resource for resource in resources}

    def list_resources(self) -> list[ResearchResource]:
        return list(self._resources.values())

    def get(self, resource_id: str) -> ResearchResource | None:
        return self._resources.get(resource_id)

    def register_existing(self, resources: Iterable[ResearchResource]) -> None:
        """把持久化层或 Parent State 已确认的全局资源加入匹配视图。"""
        self._resources.update({resource.id: resource for resource in resources})

    def canonical_key(
        self, resource_or_candidate: ResourceCandidate | ResearchResource
    ) -> str | None:
        """生成所有去重与持久化流程共用的稳定 canonical key。"""
        identity = _canonical_identity(resource_or_candidate)
        if identity is None:
            return None
        identity_type, value = identity
        if identity_type in {"repository", "dataset", "model"}:
            return f"{identity_type}:{value}"
        return f"paper:{identity_type}:{value}"

    def deduplicate(self, candidate: ResourceCandidate) -> DeduplicationResult:
        """只使用确定性强身份匹配，信息不足时返回 ambiguous。"""
        kind = candidate.kind
        canonical_key = self.canonical_key(candidate)
        if canonical_key is None:
            return DeduplicationResult(status="ambiguous", candidate=candidate)

        identity = _canonical_identity(candidate)
        assert identity is not None
        matched_by, _ = identity
        for resource in self._resources.values():
            if resource.kind != kind:
                continue
            if self.canonical_key(resource) == canonical_key:
                return DeduplicationResult(
                    status="existing",
                    candidate=candidate,
                    existing_resource=resource,
                    matched_by=matched_by,
                )
        return DeduplicationResult(status="new", candidate=candidate)
