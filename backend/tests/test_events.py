"""Tests for the event bus and the tool-call observability wrapper."""

import pytest

from taskos.core.events import EventBus, ObservedTools
from taskos.core.models import AgentType, Event, EventType, Task
from taskos.mcp_client.client import ToolResult
from taskos.store.memory import MemoryStore

RUN_ID = "run_test"


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


async def test_emit_persists_the_event_to_the_store(store):
    bus = EventBus(store)
    event = Event(run_id=RUN_ID, event_type=EventType.RUN_CREATED, payload={"goal": "test"})

    await bus.emit(event)

    persisted = await store.get_events(RUN_ID)
    assert len(persisted) == 1
    assert persisted[0].event_type is EventType.RUN_CREATED
    assert persisted[0].payload == {"goal": "test"}


async def test_every_subscriber_is_notified_in_order(store):
    bus = EventBus(store)
    received: list[str] = []

    async def sub_a(event: Event) -> None:
        received.append(f"a:{event.event_type.value}")

    async def sub_b(event: Event) -> None:
        received.append(f"b:{event.event_type.value}")

    bus.subscribe(sub_a)
    bus.subscribe(sub_b)

    await bus.emit(Event(run_id=RUN_ID, event_type=EventType.TASK_STARTED))

    assert received == ["a:task_started", "b:task_started"]


async def test_a_broken_subscriber_does_not_stop_emission_or_other_subscribers(store):
    """A dead websocket connection must never take down the run."""
    bus = EventBus(store)
    received: list[str] = []

    async def broken_sub(event: Event) -> None:
        raise ConnectionError("client disconnected")

    async def healthy_sub(event: Event) -> None:
        received.append("got it")

    bus.subscribe(broken_sub)
    bus.subscribe(healthy_sub)

    await bus.emit(Event(run_id=RUN_ID, event_type=EventType.TASK_STARTED))  # must not raise

    assert received == ["got it"]
    assert len(await store.get_events(RUN_ID)) == 1  # persistence still happened


# -- ObservedTools -----------------------------------------------------


class FakeTools:
    def __init__(self, result: ToolResult) -> None:
        self._result = result
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, params: dict) -> ToolResult:
        self.calls.append((name, params))
        return self._result


def make_task() -> Task:
    return Task(run_id=RUN_ID, description="research something", assigned_agent=AgentType.RESEARCH)


async def test_observed_tools_forwards_the_call_and_returns_the_real_result(store):
    result = ToolResult(tool="search", server="search", params={}, ok=True, duration_ms=5, content={"n": 1})
    fake = FakeTools(result)
    bus = EventBus(store)
    observed = ObservedTools(fake, bus, make_task())

    returned = await observed.call_tool("search", {"query": "x"})

    assert returned is result
    assert fake.calls == [("search", {"query": "x"})]


async def test_observed_tools_emits_a_tool_call_event_without_the_agent_knowing(store):
    """This is the whole point: research.py just calls tools.call_tool() and
    gets an event for free -- no agent code changes for observability."""
    result = ToolResult(
        tool="search", server="search", params={"query": "x"}, ok=True,
        duration_ms=12, content={"result_count": 2},
    )
    fake = FakeTools(result)
    bus = EventBus(store)
    task = make_task()
    observed = ObservedTools(fake, bus, task)

    await observed.call_tool("search", {"query": "x"})

    events = await store.get_events(RUN_ID)
    assert len(events) == 1
    assert events[0].event_type is EventType.TOOL_CALL
    assert events[0].task_id == task.task_id
    assert events[0].agent_id == "research"
    assert events[0].payload["tool"] == "search"
    assert events[0].payload["ok"] is True
    assert events[0].payload["durationMs"] == 12


async def test_observed_tools_emits_an_event_even_when_the_tool_call_fails(store):
    failure = ToolResult(
        tool="search", server="search", params={}, ok=False, duration_ms=3,
        error="Tavily rate limit hit (429).",
    )
    fake = FakeTools(failure)
    bus = EventBus(store)
    observed = ObservedTools(fake, bus, make_task())

    await observed.call_tool("search", {})

    events = await store.get_events(RUN_ID)
    assert events[0].payload["ok"] is False
    assert events[0].payload["error"] == "Tavily rate limit hit (429)."
