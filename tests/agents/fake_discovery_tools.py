"""DiscoveryAgent V1 测试使用的 deterministic 四类 Search Tool 与 Admission Fake。"""

from dataclasses import dataclass, field
from typing import Any

from langchain.tools import tool
from langchain_core.tools import BaseTool

from scitrace.models import (
    DatasetResource,
    ModelResource,
    PaperResource,
    RepositoryResource,
    ResearchResource,
    WebLocation,
)
from scitrace.models.discovery import (
    DatasetCandidate,
    ModelCandidate,
    PaperCandidate,
    RepositoryCandidate,
    ResourceCandidate,
)
from scitrace.services import ResourceService


@dataclass
class DiscoveryToolRecorder:
    """记录 DiscoveryAgent 内部每一次 Search Tool 调用及固定外部事实。"""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, tool_name: str, args: dict[str, Any], result: Any) -> None:
        serialized = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in result
        ]
        self.calls.append({"tool": tool_name, "args": args, "result": serialized})


class FakeResourceVerifier:
    """Admission 使用的确定性 Verifier；不作为 LLM Tool 暴露。"""

    def __init__(self) -> None:
        self.calls: list[ResourceCandidate] = []

    def verify(self, candidate: ResourceCandidate) -> ResearchResource | None:
        self.calls.append(candidate)
        kind = candidate.kind
        if candidate.metadata.get("verification_should_fail"):
            return None
        if kind == "paper":
            return PaperResource(
                id="paper-zipit",
                name=candidate.name,
                doi=candidate.doi,
                arxiv_id=candidate.arxiv_id,
                locations=candidate.locations,
                metadata={"source": "fake-paper-provider"},
            )
        if kind == "repository":
            return RepositoryResource(
                id="repository-zipit",
                name=f"{candidate.owner}/{candidate.repository}",
                revision="fake-tested-revision",
                locations=candidate.locations,
                metadata={
                    "provider": candidate.provider,
                    "owner": candidate.owner,
                    "repository": candidate.repository,
                },
            )
        if kind == "dataset":
            return DatasetResource(
                id="dataset-cifar10",
                name="CIFAR-10",
                version=candidate.version,
                locations=candidate.locations,
                metadata={
                    "provider": candidate.provider,
                    "dataset_id": candidate.dataset_id,
                },
            )
        if kind == "model":
            return ModelResource(
                id="model-zipit-checkpoint",
                name="ZIPIT checkpoint",
                revision=candidate.revision,
                locations=candidate.locations,
                metadata={
                    "provider": candidate.provider,
                    "model_id": candidate.model_id,
                },
            )
        return None


class InMemoryResourceRepository:
    """测试专用 ResourceRepository fake，模拟原子准入与 Task 关联。"""

    def __init__(self, resource_service: ResourceService) -> None:
        self._resource_service = resource_service
        self.persist_count = 0
        self.attachments: set[tuple[str, str]] = set()

    def admit_verified(
        self, resource: ResearchResource, *, canonical_key: str
    ) -> ResearchResource:
        for existing in self._resource_service.list_resources():
            if self._resource_service.canonical_key(existing) == canonical_key:
                return existing
        self.persist_count += 1
        self._resource_service.register_existing([resource])
        return resource

    def attach_to_task(self, task_id: str, resource_id: str) -> None:
        self.attachments.add((task_id, resource_id))


def build_fake_discovery_tools(
    recorder: DiscoveryToolRecorder,
) -> tuple[BaseTool, ...]:
    """构造四类固定 Search World；工具只返回 Candidate 事实。"""

    @tool("search_papers")
    def search_papers(query: str) -> list[dict[str, Any]]:
        """Search for paper candidates by title, author, DOI, arXiv ID, topic, or claim."""
        result = [
            PaperCandidate(
                name="ZIPIT! Merging Models from Different Tasks without Training",
                arxiv_id="2305.03053",
                doi="10.48550/arXiv.2305.03053",
                locations=[WebLocation(url="https://arxiv.org/abs/2305.03053")],
                metadata={"authors": ["A. Stoica et al."]},
            )
        ]
        recorder.record("search_papers", {"query": query}, result)
        return [candidate.model_dump(mode="json") for candidate in result]

    @tool("search_repositories")
    def search_repositories(query: str) -> list[dict[str, Any]]:
        """Search for repository candidates by project, owner, paper, or method name."""
        result = [
            RepositoryCandidate(
                name="ml-research/zipit",
                provider="github.com",
                owner="ml-research",
                repository="zipit",
                locations=[WebLocation(url="https://github.com/ml-research/zipit")],
            )
        ]
        recorder.record("search_repositories", {"query": query}, result)
        return [candidate.model_dump(mode="json") for candidate in result]

    @tool("search_datasets")
    def search_datasets(query: str) -> list[dict[str, Any]]:
        """Search for dataset candidates by provider, dataset ID, task, or paper."""
        result = [
            DatasetCandidate(
                name="CIFAR-10",
                provider="torchvision",
                dataset_id="cifar10",
                version="1",
                locations=[WebLocation(url="https://www.cs.toronto.edu/~kriz/cifar.html")],
            )
        ]
        recorder.record("search_datasets", {"query": query}, result)
        return [candidate.model_dump(mode="json") for candidate in result]

    @tool("search_models")
    def search_models(query: str) -> list[dict[str, Any]]:
        """Search for model candidates by provider, model ID, task, or paper."""
        result = [
            ModelCandidate(
                name="ZIPIT checkpoint",
                provider="huggingface.co",
                model_id="ml-research/zipit-checkpoint",
                revision="fake-revision",
                locations=[WebLocation(url="https://huggingface.co/ml-research/zipit-checkpoint")],
            )
        ]
        recorder.record("search_models", {"query": query}, result)
        return [candidate.model_dump(mode="json") for candidate in result]

    return search_papers, search_repositories, search_datasets, search_models
