"""DiscoveryAgent V2 测试使用的 deterministic Search Tools。"""

from dataclasses import dataclass, field
from typing import Any

from langchain.tools import tool
from langchain_core.tools import BaseTool

from scitrace.models import PaperResource, RepositoryResource, WebLocation


@dataclass
class DiscoveryToolRecorder:
    """记录 DiscoveryAgent 内部每一次工具调用及其固定返回值。"""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, tool_name: str, args: dict[str, Any], result: Any) -> None:
        self.calls.append({"tool": tool_name, "args": args, "result": result})


def build_fake_discovery_tools(
    recorder: DiscoveryToolRecorder,
) -> tuple[BaseTool, ...]:
    """构造 Paper + Repository 固定测试世界，不提供任何下一步提示。"""

    @tool("search_papers")
    def search_papers(query: str) -> list[dict[str, Any]]:
        """Search only for paper resources matching a title, author, DOI, topic, or claim.

        This tool does not return repository resources, so a repository requested by the
        delegation remains unresolved after using this tool.
        """
        resource = PaperResource(
            id="paper-zipit",
            name="ZIPIT! Merging Models from Different Tasks without Training",
            arxiv_id="2305.03053",
            locations=[WebLocation(url="https://arxiv.org/abs/2305.03053")],
            metadata={"source": "fake-arxiv", "stub": True},
        )
        result = [resource.model_dump(mode="json")]
        recorder.record("search_papers", {"query": query}, result)
        return result

    @tool("search_repositories")
    def search_repositories(query: str) -> list[dict[str, Any]]:
        """Search only for repository resources related to a paper, method, author, or project.

        Use this capability when the delegation requests a repository; finding a paper alone
        does not provide a repository resource.
        """
        resource = RepositoryResource(
            id="repository-zipit",
            name="ml-research/zipit",
            revision="fake-tested-revision",
            locations=[WebLocation(url="https://github.com/ml-research/zipit")],
            metadata={
                "source": "fake-github",
                "related_paper_id": "paper-zipit",
                "stub": True,
            },
        )
        result = [resource.model_dump(mode="json")]
        recorder.record("search_repositories", {"query": query}, result)
        return result

    return search_papers, search_repositories
