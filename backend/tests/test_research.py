"""Tests for the Research agent.

The MCP tool call and the LLM summary call are both faked, so these run
instantly and prove the agent's own logic: how it reacts to tool failure,
empty results, and success -- not Tavily's or Gemini's behavior.
"""

import pytest

from taskos.agents import research
from taskos.agents.errors import EmptyResultError, ToolCallError
from taskos.core.models import AgentType, Task
from taskos.mcp_client.client import ToolResult
from taskos.store.memory import MemoryStore

RUN_ID = "run_test"


def make_task() -> Task:
    return Task(run_id=RUN_ID, description="Research Anthropic", assigned_agent=AgentType.RESEARCH)


class FakeTools:
    """Stands in for MCPClientManager: returns a canned ToolResult."""

    def __init__(self, result: ToolResult) -> None:
        self._result = result
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, params: dict) -> ToolResult:
        self.calls.append((name, params))
        return self._result


def search_success(results: list[dict] | None = None) -> ToolResult:
    return ToolResult(
        tool="search",
        server="search",
        params={},
        ok=True,
        duration_ms=5,
        content={
            "query": "Anthropic",
            "answer": "Anthropic is an AI safety company.",
            "results": results if results is not None else [
                {"title": "Anthropic", "url": "https://anthropic.com", "content": "AI safety lab."},
            ],
            "result_count": 1 if results is None else len(results),
        },
    )


def search_failure() -> ToolResult:
    return ToolResult(
        tool="search", server="search", params={}, ok=False, duration_ms=5,
        error="Tavily rate limit hit (429).",
    )


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


async def test_successful_search_writes_findings_to_state(monkeypatch, store):
    async def fake_generate_text(prompt, *, system_instruction=None):
        return "Anthropic is an AI safety and research company known for Claude."

    monkeypatch.setattr(research, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(search_success())

    findings = await research.run(task, tools=tools, store=store)

    assert findings["summary"].startswith("Anthropic is an AI safety")
    assert findings["sources"] == [{"title": "Anthropic", "url": "https://anthropic.com"}]
    assert tools.calls == [("search", {"query": task.description, "max_results": research.MAX_RESULTS})]

    stored = await store.read_state(RUN_ID, task.task_id)
    assert stored["findings"] == findings


async def test_tool_failure_raises_tool_call_error(store):
    task = make_task()
    tools = FakeTools(search_failure())

    with pytest.raises(ToolCallError, match="rate limit"):
        await research.run(task, tools=tools, store=store)


async def test_empty_results_raise_empty_result_error(store):
    task = make_task()
    tools = FakeTools(search_success(results=[]))

    with pytest.raises(EmptyResultError, match="No search results"):
        await research.run(task, tools=tools, store=store)


async def test_empty_results_never_reach_the_llm_or_the_store(monkeypatch, store):
    """An empty result should fail fast -- no wasted LLM call, no state write."""
    called = False

    async def fake_generate_text(*args, **kwargs):
        nonlocal called
        called = True
        return "should not be called"

    monkeypatch.setattr(research, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(search_success(results=[]))

    with pytest.raises(EmptyResultError):
        await research.run(task, tools=tools, store=store)

    assert called is False
    assert await store.read_state(RUN_ID, task.task_id) == {}
