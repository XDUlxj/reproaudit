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
from scitrace.services import ResourceService


@dataclass
class DiscoveryToolRecorder:
    """记录 DiscoveryAgent 内部每一次 Search Tool 调用及固定外部事实。"""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, tool_name: str, args: dict[str, Any], result: Any) -> None:
        self.calls.append({"tool": tool_name, "args": args, "result": result})


class FakeResourceVerifier:
    """Admission 使用的确定性 Verifier；不作为 LLM Tool 暴露。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def verify(self, candidate: dict[str, Any]) -> ResearchResource | None:
        self.calls.append(candidate)
        kind = candidate.get("kind")
        if candidate.get("verification_should_fail"):
            return None
        if kind == "paper":
            return PaperResource(
                id="paper-zipit",
                name=str(candidate.get("title", "ZIPIT Paper")),
                doi=candidate.get("doi"),
                arxiv_id=candidate.get("arxiv_id"),
                locations=[WebLocation(url=str(candidate["url"]))],
                metadata={"source": "fake-paper-provider"},
            )
        if kind == "repository":
            return RepositoryResource(
                id="repository-zipit",
                name=f"{candidate['owner']}/{candidate['name']}",
                revision="fake-tested-revision",
                locations=[WebLocation(url=str(candidate["url"]).removesuffix(".git"))],
                metadata={
                    "provider": candidate["provider"],
                    "owner": candidate["owner"],
                },
            )
        if kind == "dataset":
            return DatasetResource(
                id="dataset-cifar10",
                name="CIFAR-10",
                version=str(candidate["version"]),
                locations=[WebLocation(url=str(candidate["url"]))],
                metadata={
                    "provider": candidate["provider"],
                    "dataset_id": candidate["dataset_id"],
                },
            )
        if kind == "model":
            return ModelResource(
                id="model-zipit-checkpoint",
                name="ZIPIT checkpoint",
                revision=str(candidate["revision"]),
                locations=[WebLocation(url=str(candidate["url"]))],
                metadata={
                    "provider": candidate["provider"],
                    "model_id": candidate["model_id"],
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
        candidate = resource.model_dump(mode="json")
        candidate.update(resource.metadata)
        if resource.kind == "repository" and resource.locations:
            location = resource.locations[0]
            if location.kind == "web":
                candidate["url"] = location.url
        final = self._resource_service.deduplicate(candidate)
        if final.status == "existing":
            assert final.existing_resource is not None
            return final.existing_resource
        if final.status == "ambiguous":
            raise ValueError("Persistence 不接受身份不明确的 Resource")
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
            {
                "kind": "paper",
                "title": "ZIPIT! Merging Models from Different Tasks without Training",
                "authors": ["A. Stoica et al."],
                "arxiv_id": "2305.03053",
                "doi": "10.48550/arXiv.2305.03053",
                "url": "https://arxiv.org/abs/2305.03053",
            }
        ]
        recorder.record("search_papers", {"query": query}, result)
        return result

    @tool("search_repositories")
    def search_repositories(query: str) -> list[dict[str, Any]]:
        """Search for repository candidates by project, owner, paper, or method name."""
        result = [
            {
                "kind": "repository",
                "provider": "github.com",
                "owner": "ml-research",
                "name": "zipit",
                "url": "https://github.com/ml-research/zipit.git",
            }
        ]
        recorder.record("search_repositories", {"query": query}, result)
        return result

    @tool("search_datasets")
    def search_datasets(query: str) -> list[dict[str, Any]]:
        """Search for dataset candidates by provider, dataset ID, task, or paper."""
        result = [
            {
                "kind": "dataset",
                "provider": "torchvision",
                "dataset_id": "cifar10",
                "version": "1",
                "name": "CIFAR-10",
                "url": "https://www.cs.toronto.edu/~kriz/cifar.html",
            }
        ]
        recorder.record("search_datasets", {"query": query}, result)
        return result

    @tool("search_models")
    def search_models(query: str) -> list[dict[str, Any]]:
        """Search for model candidates by provider, model ID, task, or paper."""
        result = [
            {
                "kind": "model",
                "provider": "huggingface.co",
                "model_id": "ml-research/zipit-checkpoint",
                "revision": "fake-revision",
                "name": "ZIPIT checkpoint",
                "url": "https://huggingface.co/ml-research/zipit-checkpoint",
            }
        ]
        recorder.record("search_models", {"query": query}, result)
        return result

    return search_papers, search_repositories, search_datasets, search_models
