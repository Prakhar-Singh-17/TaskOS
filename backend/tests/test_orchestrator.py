"""Tests for the orchestrator: goal -> plan -> run, wired end to end.

supervisor.plan() and run_graph() are both faked here -- they're already
covered by their own test suites (test_supervisor.py, test_runner.py). These
tests prove the wiring: does the orchestrator persist what it should, emit
the events it should, and handle a planning failure without crashing.
"""

import pytest

from taskos.core import orchestrator
from taskos.agents.llm import LLMMalformedOutputError
from taskos.core.events import EventBus
from taskos.core.models import AgentType, EventType, Run, RunStatus, Task
from taskos.store.memory import MemoryStore


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


def make_plan(goal: str) -> Run:
    """A plan shaped like what supervisor.plan() would really return --
    note these tasks carry a *different* run_id, matching reality: the
    Supervisor builds its own Run/task ids before the orchestrator exists."""
    planned = Run(goal=goal)
    planned.tasks = [
        Task(run_id=planned.run_id, description="research it", assigned_agent=AgentType.RESEARCH),
    ]
    return planned


async def test_happy_path_persists_plan_and_runs_it(monkeypatch, store):
    async def fake_plan(goal: str) -> Run:
        return make_plan(goal)

    async def fake_run_graph(run, *, tools, store, events, max_parallel_tasks=None):
        run.status = RunStatus.COMPLETED
        return run

    monkeypatch.setattr(orchestrator.supervisor, "plan", fake_plan)
    monkeypatch.setattr(orchestrator, "run_graph", fake_run_graph)

    events = EventBus(store)
    result = await orchestrator.execute_goal("test goal", tools=None, store=store, events=events)

    assert result.status is RunStatus.COMPLETED
    assert len(result.tasks) == 1
    # The task was re-homed onto the orchestrator's run_id, not the
    # Supervisor's internal one.
    assert result.tasks[0].run_id == result.run_id

    persisted_run = await store.get_run(result.run_id)
    assert persisted_run is not None
    assert len(persisted_run.tasks) == 1

    emitted = [e.event_type for e in await store.get_events(result.run_id)]
    assert emitted == [EventType.RUN_CREATED, EventType.PLAN_CREATED]


async def test_plan_created_event_includes_tasks_and_layers(monkeypatch, store):
    async def fake_plan(goal: str) -> Run:
        return make_plan(goal)

    async def fake_run_graph(run, *, tools, store, events, max_parallel_tasks=None):
        return run

    monkeypatch.setattr(orchestrator.supervisor, "plan", fake_plan)
    monkeypatch.setattr(orchestrator, "run_graph", fake_run_graph)

    events = EventBus(store)
    result = await orchestrator.execute_goal("test goal", tools=None, store=store, events=events)

    plan_event = next(e for e in await store.get_events(result.run_id) if e.event_type is EventType.PLAN_CREATED)
    assert plan_event.payload["tasks"][0]["agent"] == "research"
    assert plan_event.payload["layers"] == [[result.tasks[0].task_id]]


async def test_planning_failure_produces_a_failed_run_without_crashing(monkeypatch, store):
    async def failing_plan(goal: str) -> Run:
        raise LLMMalformedOutputError("model returned garbage")

    monkeypatch.setattr(orchestrator.supervisor, "plan", failing_plan)

    events = EventBus(store)
    result = await orchestrator.execute_goal("test goal", tools=None, store=store, events=events)

    assert result.status is RunStatus.FAILED
    assert "model returned garbage" in result.error
    assert result.tasks == []

    emitted = [e.event_type for e in await store.get_events(result.run_id)]
    assert emitted == [EventType.RUN_CREATED, EventType.RUN_COMPLETED]
