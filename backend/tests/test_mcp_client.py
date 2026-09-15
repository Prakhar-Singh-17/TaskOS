"""End-to-end tests for the MCP client layer.

These spawn the real search MCP server as a subprocess and speak MCP over
stdio, so they prove discovery and invocation, not just local function calls.
"""

import pytest

from taskos.mcp_client.client import MCPClientManager


@pytest.fixture
async def tools():
    async with MCPClientManager() as manager:
        yield manager


async def test_discovers_search_tool_from_server(tools):
    specs = tools.list_tools()
    assert [s.name for s in specs] == ["search"]
    assert specs[0].server == "search"
    assert "query" in specs[0].input_schema.get("properties", {})


async def test_tool_catalogue_shape_for_llm(tools):
    catalogue = tools.describe_tools()
    assert catalogue[0].keys() == {"name", "description", "parameters"}


async def test_call_tool_returns_structured_content(tools):
    result = await tools.call_tool("search", {"query": "DAG orchestration", "max_results": 2})
    assert result.ok
    assert result.server == "search"
    assert result.content["result_count"] == 2
    assert result.duration_ms >= 0


async def test_unknown_tool_fails_without_raising(tools):
    result = await tools.call_tool("does_not_exist", {})
    assert not result.ok
    assert "Unknown tool" in result.error


async def test_empty_results_are_a_success_not_an_error(tools):
    """Empty results must surface as ok=True so the runtime -- not the
    transport -- decides they are a retryable outcome."""
    result = await tools.call_tool("search", {"query": "__no_results__"})
    assert result.ok
    assert result.content["result_count"] == 0


async def test_tool_result_serializes_for_the_event_log(tools):
    result = await tools.call_tool("search", {"query": "observability"})
    payload = result.to_event_payload()
    assert payload["tool"] == "search"
    assert payload["ok"] is True
    assert payload["error"] is None
