"""Tests for the Coder agent.

Both the MCP tool call and the Gemini call are faked, so these run instantly
and prove the agent's own logic -- how it reacts to a sandbox success/failure,
and whether it actually feeds a previous error back into the next prompt --
not Judge0's or Gemini's real behavior.
"""

import pytest

from taskos.agents import coder
from taskos.agents.errors import CodeExecutionError, ToolCallError
from taskos.core.models import AgentType, Attempt, FailureKind, Task
from taskos.mcp_client.client import ToolResult
from taskos.store.memory import MemoryStore

RUN_ID = "run_test"


def make_task(attempts: list[Attempt] | None = None) -> Task:
    task = Task(
        run_id=RUN_ID,
        description="Check whether 97 is prime",
        assigned_agent=AgentType.CODER,
    )
    if attempts:
        task.attempts = attempts
    return task


class FakeTools:
    """Stands in for MCPClientManager: returns a canned ToolResult."""

    def __init__(self, result: ToolResult) -> None:
        self._result = result
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, params: dict) -> ToolResult:
        self.calls.append((name, params))
        return self._result


def execution_success() -> ToolResult:
    return ToolResult(
        tool="execute_code", server="code", params={}, ok=True, duration_ms=200,
        content={"stdout": "97 is prime\n", "stderr": "", "exitOk": True, "note": "Accepted"},
    )


def execution_failure() -> ToolResult:
    return ToolResult(
        tool="execute_code", server="code", params={}, ok=True, duration_ms=150,
        content={"stdout": "", "stderr": "NameError: name 'isprime' is not defined", "exitOk": False, "note": "Runtime Error"},
    )


def tool_call_failure() -> ToolResult:
    return ToolResult(
        tool="execute_code", server="code", params={}, ok=False, duration_ms=5,
        error="Judge0 rate limit hit (429).",
    )


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


async def test_successful_run_writes_code_result_to_state(monkeypatch, store):
    async def fake_generate_text(prompt, *, system_instruction=None):
        return "print('97 is prime')"

    monkeypatch.setattr(coder, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(execution_success())

    result = await coder.run(task, tools=tools, store=store)

    assert result["summary"] == f"Ran code for: {task.description}"
    assert result["code"]["source"] == "print('97 is prime')"
    assert result["code"]["stdout"] == "97 is prime\n"

    stored = await store.read_state(RUN_ID, task.task_id)
    assert stored["code_result"] == result


async def test_python_fence_is_parsed_into_code_and_language(monkeypatch, store):
    async def fake_generate_text(prompt, *, system_instruction=None):
        return "```python\nprint('hi')\n```"

    monkeypatch.setattr(coder, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(execution_success())

    result = await coder.run(task, tools=tools, store=store)

    assert result["code"]["source"] == "print('hi')"
    assert result["code"]["language"] == "python"
    assert tools.calls == [("execute_code", {"code": "print('hi')", "language": "python"})]


async def test_javascript_fence_is_parsed_and_passed_through(monkeypatch, store):
    async def fake_generate_text(prompt, *, system_instruction=None):
        return "```javascript\nconsole.log('hi')\n```"

    monkeypatch.setattr(coder, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(execution_success())

    result = await coder.run(task, tools=tools, store=store)

    assert result["code"]["source"] == "console.log('hi')"
    assert result["code"]["language"] == "javascript"
    assert tools.calls == [("execute_code", {"code": "console.log('hi')", "language": "javascript"})]


async def test_missing_fence_defaults_to_python(monkeypatch, store):
    async def fake_generate_text(prompt, *, system_instruction=None):
        return "print('no fence here')"

    monkeypatch.setattr(coder, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(execution_success())

    result = await coder.run(task, tools=tools, store=store)

    assert result["code"]["language"] == "python"


async def test_tool_call_failure_raises_tool_call_error(monkeypatch, store):
    async def fake_generate_text(prompt, *, system_instruction=None):
        return "print(1)"

    monkeypatch.setattr(coder, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(tool_call_failure())

    with pytest.raises(ToolCallError, match="rate limit"):
        await coder.run(task, tools=tools, store=store)

    assert await store.read_state(RUN_ID, task.task_id) == {}


async def test_code_execution_failure_raises_code_execution_error(monkeypatch, store):
    async def fake_generate_text(prompt, *, system_instruction=None):
        return "print(isprime(97))"

    monkeypatch.setattr(coder, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(execution_failure())

    with pytest.raises(CodeExecutionError, match="NameError"):
        await coder.run(task, tools=tools, store=store)


async def test_a_note_marked_draft_is_never_executed(monkeypatch, store):
    """Gemini flagging its own code as unverifiable (a leading NOTE: line)
    must skip execute_code entirely -- retrying a live-network task three
    times would just fail the same way three times."""
    async def fake_generate_text(prompt, *, system_instruction=None):
        return "NOTE: needs a live MongoDB connection\n```javascript\nconsole.log('connect')\n```"

    monkeypatch.setattr(coder, "generate_text", fake_generate_text)
    task = make_task()
    tools = FakeTools(execution_success())

    result = await coder.run(task, tools=tools, store=store)

    assert tools.calls == []  # never attempted
    assert result["summary"] == f"Drafted code for: {task.description}"
    assert result["code"]["source"] == "console.log('connect')"
    assert result["code"]["language"] == "javascript"
    assert result["code"]["stdout"] is None
    assert result["code"]["note"] == "needs a live MongoDB connection"

    stored = await store.read_state(RUN_ID, task.task_id)
    assert stored["code_result"] == result


async def test_a_prior_failed_attempts_error_is_fed_into_the_next_prompt(monkeypatch, store):
    """The self-correction claim: no prepare_retry hook exists for Coder --
    it reads task.attempts (already populated by the runner before the next
    call) and must actually put the previous error in the next prompt."""
    seen_prompts: list[str] = []

    async def fake_generate_text(prompt, *, system_instruction=None):
        seen_prompts.append(prompt)
        return "print(97)"

    monkeypatch.setattr(coder, "generate_text", fake_generate_text)
    task = make_task(attempts=[
        Attempt(number=1, ok=False, failure_kind=FailureKind.CODE_FAILED,
                error="NameError: name 'isprime' is not defined"),
    ])
    tools = FakeTools(execution_success())

    await coder.run(task, tools=tools, store=store)

    assert len(seen_prompts) == 1
    assert "NameError: name 'isprime' is not defined" in seen_prompts[0]
    assert "Fix the code" in seen_prompts[0]
