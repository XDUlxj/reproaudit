"""DiscoveryAgent V1 Fake Search World 的能力边界测试。"""

from tests.agents.fake_discovery_tools import (
    DiscoveryToolRecorder,
    build_fake_discovery_tools,
)


def test_fake_world_exposes_only_four_search_tools_without_steering_fields() -> None:
    recorder = DiscoveryToolRecorder()
    tools = build_fake_discovery_tools(recorder)

    assert {tool.name for tool in tools} == {
        "search_papers",
        "search_repositories",
        "search_datasets",
        "search_models",
    }
    forbidden = {
        "next_tool",
        "next_agent",
        "should_continue",
        "enough_resources",
        "discovery_complete",
        "required_specialist",
        "required_inspection_tool",
    }
    for search_tool in tools:
        result = search_tool.invoke({"query": "test"})
        assert result
        assert forbidden.isdisjoint(result[0])
