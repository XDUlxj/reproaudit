"""DiscoveryAgent V1 测试使用的 deterministic Search/Resolve/Verify Tools。"""

from dataclasses import dataclass, field
from typing import Any

from langchain.tools import tool
from langchain_core.tools import BaseTool

from scitrace.models import PaperResource, RepositoryResource, WebLocation


@dataclass
class DiscoveryToolRecorder:
    """记录 DiscoveryAgent 内部每一次工具调用及固定外部事实。"""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, tool_name: str, args: dict[str, Any], result: Any) -> None:
        self.calls.append({"tool": tool_name, "args": args, "result": result})


def build_fake_discovery_tools(
    recorder: DiscoveryToolRecorder,
) -> tuple[BaseTool, ...]:
    """构造固定外部世界；工具仅返回事实，不提示下一步动作。"""

    @tool("search_papers")
    def search_papers(query: str) -> list[dict[str, Any]]:
        """Search for paper candidates; results are candidates, not confirmed resources."""
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
        """Search for repository candidates; results are candidates, not confirmed resources."""
        result = [
            {
                "kind": "repository",
                "provider": "github.com",
                "owner": "ml-research",
                "name": "zipit",
                "url": "https://github.com/ml-research/zipit.git",
                "fork": False,
                "description": "Code associated with ZIPIT model merging research.",
            }
        ]
        recorder.record("search_repositories", {"query": query}, result)
        return result

    @tool("resolve_resource_identity")
    def resolve_resource_identity(candidate: dict[str, Any]) -> dict[str, Any]:
        """Resolve only canonical identity fields for a paper or repository candidate."""
        kind = candidate.get("kind")
        if kind == "paper":
            result = {
                **candidate,
                "title": "ZIPIT! Merging Models from Different Tasks without Training",
                "arxiv_id": "2305.03053",
                "doi": "10.48550/arXiv.2305.03053",
                "canonical_url": "https://arxiv.org/abs/2305.03053",
            }
        elif kind == "repository":
            result = {
                **candidate,
                "provider": "github.com",
                "owner": "ml-research",
                "name": "zipit",
                "canonical_url": "https://github.com/ml-research/zipit",
                "revision": "fake-tested-revision",
            }
        else:
            raise ValueError(f"unsupported candidate kind: {kind}")
        recorder.record("resolve_resource_identity", {"candidate": candidate}, result)
        return result

    @tool("verify_resource")
    def verify_resource(candidate: dict[str, Any]) -> dict[str, Any]:
        """Verify a candidate and return the only Resource eligible for final promotion.

        The verified_resource is authoritative: preserve its ID and metadata exactly when
        including it in DiscoveryResult.
        """
        kind = candidate.get("kind")
        if kind == "paper":
            resource = PaperResource(
                id="paper-zipit",
                name="ZIPIT! Merging Models from Different Tasks without Training",
                arxiv_id="2305.03053",
                doi="10.48550/arXiv.2305.03053",
                locations=[WebLocation(url="https://arxiv.org/abs/2305.03053")],
                metadata={"source": "fake-arxiv", "stub": True},
            )
            evidence = {"exists": True, "content_accessible": True}
        elif kind == "repository":
            resource = RepositoryResource(
                id="repository-zipit",
                name="ml-research/zipit",
                revision="fake-tested-revision",
                locations=[WebLocation(url="https://github.com/ml-research/zipit")],
                metadata={
                    "source": "fake-github",
                    "provenance": "unknown",
                    "stub": True,
                },
            )
            evidence = {
                "exists": True,
                "accessible": True,
                "revision_resolvable": True,
                "provenance": "unknown",
            }
        else:
            raise ValueError(f"unsupported candidate kind: {kind}")
        result = {
            "verified_resource": resource.model_dump(mode="json"),
            "evidence": evidence,
        }
        recorder.record("verify_resource", {"candidate": candidate}, result)
        return result

    return (
        search_papers,
        search_repositories,
        resolve_resource_identity,
        verify_resource,
    )
