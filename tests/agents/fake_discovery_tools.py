"""真实 DiscoveryAgent 测试使用的 deterministic search/inspect tools。"""

from dataclasses import dataclass, field
from typing import Any

from langchain.tools import tool
from langchain_core.tools import BaseTool

from scitrace.models import PaperResource, RepositoryResource, WebLocation


@dataclass
class DiscoveryToolRecorder:
    """记录 DiscoveryAgent 内部每一次 tool calling。"""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, tool_name: str, args: dict[str, Any], result: Any) -> None:
        self.calls.append({"tool": tool_name, "args": args, "result": result})


def build_fake_discovery_tools(
    recorder: DiscoveryToolRecorder,
) -> tuple[BaseTool, ...]:
    """构造固定候选世界；Search 返回 candidate，Inspect 才返回 Resource。"""

    @tool("search_papers")
    def search_papers(query: str) -> list[dict[str, str]]:
        """Search for paper candidates matching a title, topic, author, DOI, or claim."""
        result = [
            {
                "candidate_id": "paper-candidate-zipit",
                "title": "ZIPIT! Merging Models from Different Tasks without Training",
                "url": "https://arxiv.org/abs/2305.03053",
                "source": "fake-arxiv",
                "verification_status": "unverified",
                "required_inspection_tool": "inspect_paper",
            }
        ]
        recorder.record("search_papers", {"query": query}, result)
        return result

    @tool("inspect_paper")
    def inspect_paper(candidate_id: str) -> dict[str, Any]:
        """Inspect and verify a paper candidate before accepting it as a resource."""
        if candidate_id not in {"paper-candidate-zipit", "paper-zipit"}:
            raise ValueError(f"unknown paper candidate: {candidate_id}")
        resource = PaperResource(
            id="paper-zipit",
            name="ZIPIT! Merging Models from Different Tasks without Training",
            arxiv_id="2305.03053",
            locations=[WebLocation(url="https://arxiv.org/abs/2305.03053")],
            metadata={"verified_by": "fake_inspect_paper", "stub": True},
        )
        result = resource.model_dump(mode="json")
        recorder.record("inspect_paper", {"candidate_id": candidate_id}, result)
        return result

    @tool("search_repositories")
    def search_repositories(query: str) -> list[dict[str, str]]:
        """Search for repository candidates related to a confirmed paper or method."""
        result = [
            {
                "candidate_id": "repository-candidate-zipit",
                "name": "ml-research/zipit",
                "url": "https://github.com/ml-research/zipit",
                "source": "fake-github",
                "verification_status": "unverified",
                "required_inspection_tool": "inspect_repository",
            }
        ]
        recorder.record("search_repositories", {"query": query}, result)
        return result

    @tool("inspect_repository")
    def inspect_repository(candidate_id: str) -> dict[str, Any]:
        """Inspect and verify a repository candidate and its paper relationship."""
        if candidate_id not in {"repository-candidate-zipit", "repository-zipit"}:
            raise ValueError(f"unknown repository candidate: {candidate_id}")
        resource = RepositoryResource(
            id="repository-zipit",
            name="ml-research/zipit",
            revision="fake-tested-revision",
            locations=[WebLocation(url="https://github.com/ml-research/zipit")],
            metadata={
                "verified_by": "fake_inspect_repository",
                "related_paper_id": "paper-zipit",
                "stub": True,
            },
        )
        result = resource.model_dump(mode="json")
        recorder.record("inspect_repository", {"candidate_id": candidate_id}, result)
        return result

    return search_papers, inspect_paper, search_repositories, inspect_repository
