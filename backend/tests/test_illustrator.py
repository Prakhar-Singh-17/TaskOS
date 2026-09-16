"""Tests for the Illustrator agent.

The MCP tool call is faked, so these run instantly and prove the agent's
own logic -- how it reacts to tool success/failure and what it writes to
shared state -- not Pollinations' actual behavior (see
scripts/smoke_illustrator.py for a real, live call).
"""

import pytest

from taskos.agents import illustrator
from taskos.agents.errors import ToolCallError
from taskos.core.models import AgentType, Task
from taskos.mcp_client.client import ToolResult
from taskos.store.memory import MemoryStore

RUN_ID = "run_test"


def make_task() -> Task:
    return Task(
        run_id=RUN_ID,
        description="A red panda astronaut, flat vector style",
        assigned_agent=AgentType.ILLUSTRATOR,
    )


class FakeTools:
    """Stands in for MCPClientManager: returns a canned ToolResult."""

    def __init__(self, result: ToolResult) -> None:
        self._result = result
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, params: dict) -> ToolResult:
        self.calls.append((name, params))
        return self._result


def image_success() -> ToolResult:
    return ToolResult(
        tool="generate_image", server="image", params={}, ok=True, duration_ms=800,
        content={"prompt": "x", "mimeType": "image/jpeg", "imageBase64": "ZmFrZWJ5dGVz", "note": "pollinations"},
    )


def image_failure() -> ToolResult:
    return ToolResult(
        tool="generate_image", server="image", params={}, ok=False, duration_ms=5,
        error="Pollinations rate limit hit (429).",
    )


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


async def test_successful_generation_writes_illustration_to_state(store):
    task = make_task()
    tools = FakeTools(image_success())

    illustration = await illustrator.run(task, tools=tools, store=store)

    assert illustration["summary"] == f"Illustration: {task.description}"
    assert illustration["image"] == {"base64": "ZmFrZWJ5dGVz", "mimeType": "image/jpeg"}
    assert tools.calls == [("generate_image", {"prompt": task.description})]

    stored = await store.read_state(RUN_ID, task.task_id)
    assert stored["illustration"] == illustration


async def test_tool_failure_raises_tool_call_error(store):
    task = make_task()
    tools = FakeTools(image_failure())

    with pytest.raises(ToolCallError, match="rate limit"):
        await illustrator.run(task, tools=tools, store=store)

    assert await store.read_state(RUN_ID, task.task_id) == {}
