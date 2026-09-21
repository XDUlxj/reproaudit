"""科研资源强身份匹配服务。"""

from collections.abc import Iterable
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from scitrace.models import ResearchResource
from scitrace.models.discovery import DeduplicationResult


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
    name = _normalized_text(candidate.get("name"))
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

    def deduplicate(self, candidate: dict[str, Any]) -> DeduplicationResult:
        """只使用确定性强身份匹配，信息不足时返回 ambiguous。"""
        value = deepcopy(candidate)
        kind = value.get("kind")
        identity: tuple[str, Any] | None = None
        if kind == "paper":
            doi = _normalized_doi(value.get("doi"))
            arxiv_id = _normalized_text(value.get("arxiv_id"))
            if doi:
                identity = ("doi", doi)
            elif arxiv_id:
                identity = ("arxiv_id", arxiv_id)
        elif kind == "repository":
            repository = _repository_identity(value)
            if repository:
                identity = ("repository_identity", repository)
        elif kind == "dataset":
            provider = _normalized_text(value.get("provider"))
            dataset_id = _normalized_text(value.get("dataset_id"))
            version = _normalized_text(value.get("version"))
            if provider and dataset_id and version:
                identity = ("dataset_identity", (provider, dataset_id, version))
        elif kind == "model":
            provider = _normalized_text(value.get("provider"))
            model_id = _normalized_text(value.get("model_id"))
            revision = _normalized_text(value.get("revision"))
            if provider and model_id and revision:
                identity = ("model_identity", (provider, model_id, revision))

        if identity is None:
            return DeduplicationResult(status="ambiguous", candidate=value)

        matched_by, expected = identity
        for resource in self._resources.values():
            if resource.kind != kind:
                continue
            known = _resource_candidate(resource)
            if matched_by == "doi":
                actual = _normalized_doi(known.get("doi"))
            elif matched_by == "arxiv_id":
                actual = _normalized_text(known.get("arxiv_id"))
            elif matched_by == "repository_identity":
                actual = _repository_identity(known)
            elif matched_by == "dataset_identity":
                actual = (
                    _normalized_text(known.get("provider")),
                    _normalized_text(known.get("dataset_id")),
                    _normalized_text(known.get("version")),
                )
            else:
                actual = (
                    _normalized_text(known.get("provider")),
                    _normalized_text(known.get("model_id")),
                    _normalized_text(known.get("revision")),
                )
            if actual == expected:
                return DeduplicationResult(
                    status="existing",
                    candidate=value,
                    existing_resource=resource,
                    matched_by=matched_by,
                )
        return DeduplicationResult(status="new", candidate=value)
