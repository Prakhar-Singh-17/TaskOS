"""Unit tests for the search MCP server's tool logic (no subprocess)."""

from taskos.mcp_servers.search_server import _mock_search, search


async def test_mock_search_returns_results():
    result = await search("agentic operating systems", max_results=2)
    assert result["result_count"] == 2
    assert len(result["results"]) == 2
    assert all({"title", "url", "content", "score"} <= set(r) for r in result["results"])


async def test_empty_query_reports_no_results_instead_of_raising():
    result = await search("   ")
    assert result["result_count"] == 0
    assert result["results"] == []


async def test_forced_empty_marker_drives_the_retry_demo():
    result = await search("__no_results__ obviously nonsense")
    assert result["result_count"] == 0


async def test_max_results_is_clamped():
    result = await search("clamping", max_results=999)
    assert result["result_count"] <= 10


def test_mock_search_is_deterministic():
    assert _mock_search("same query", 3) == _mock_search("same query", 3)
