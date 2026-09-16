"""End-to-end tests for the MCP client layer.

These spawn the real search MCP server as a subprocess and speak MCP over
stdio, so they prove discovery and invocation, not just local function calls.
"""

import pytest

from taskos.mcp_client.client import MCPClientManager, ToolResult


@pytest.fixture
async def tools():
    async with MCPClientManager() as manager:
        yield manager


async def test_discovers_tools_from_every_registered_server(tools):
    specs = {s.name: s for s in tools.list_tools()}
    assert set(specs) == {"search", "generate_image"}
    assert specs["search"].server == "search"
    assert "query" in specs["search"].input_schema.get("properties", {})
    assert specs["generate_image"].server == "image"
    assert "prompt" in specs["generate_image"].input_schema.get("properties", {})


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


def test_truncate_large_strings_shrinks_long_values_only():
    from taskos.mcp_client.client import _truncate_large_strings

    small = {"title": "fine", "nested": {"also_fine": "x" * 10}}
    assert _truncate_large_strings(small) == small

    large = {"imageBase64": "x" * 1000, "mimeType": "image/png"}
    truncated = _truncate_large_strings(large)
    assert truncated["imageBase64"] == "<1000 chars, omitted from live event>"
    assert truncated["mimeType"] == "image/png"  # short fields untouched

    in_a_list = _truncate_large_strings({"sources": ["x" * 1000, "short"]})
    assert in_a_list["sources"][0] == "<1000 chars, omitted from live event>"
    assert in_a_list["sources"][1] == "short"


async def test_to_event_payload_truncates_result_but_not_the_real_content(tools):
    """The broadcast copy (to_event_payload) shrinks a large field; the real
    ToolResult.content that the task actually keeps/persists is untouched --
    only what goes out over the live event feed changes."""
    result = ToolResult(
        tool="generate_image", server="image", params={}, ok=True, duration_ms=10,
        content={"imageBase64": "x" * 1000, "mimeType": "image/png"},
    )

    payload = result.to_event_payload()

    assert payload["result"]["imageBase64"] == "<1000 chars, omitted from live event>"
    assert result.content["imageBase64"] == "x" * 1000  # unchanged
