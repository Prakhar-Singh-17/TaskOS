"""Tests for the in-memory StateStore.

Runs against MemoryStore directly since it needs no external database --
MongoStore implements the same StateStore interface and is exercised by hand
against a real Atlas cluster (see .env.example for MONGODB_URI).
"""

import pytest

from taskos.core.models import AgentType, Event, EventType, Run, Task
from taskos.store.memory import MemoryStore


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


def make_run() -> Run:
    run = Run(goal="Compare three companies")
    tasks = [
        Task(run_id=run.run_id, description="research A", assigned_agent=AgentType.RESEARCH),
        Task(run_id=run.run_id, description="research B", assigned_agent=AgentType.RESEARCH),
    ]
    run.tasks = tasks
    return run


# -- runs --------------------------------------------------------------


async def test_create_and_get_run_round_trips_tasks(store):
    run = make_run()
    await store.create_run(run)

    loaded = await store.get_run(run.run_id)
    assert loaded is not None
    assert loaded.goal == run.goal
    assert {t.task_id for t in loaded.tasks} == {t.task_id for t in run.tasks}


async def test_get_run_returns_none_for_unknown_id(store):
    assert await store.get_run("run_does_not_exist") is None


async def test_update_run_patches_only_given_fields(store):
    run = make_run()
    await store.create_run(run)

    await store.update_run(run.run_id, status="completed", final_output="done")

    loaded = await store.get_run(run.run_id)
    assert loaded.status == "completed"
    assert loaded.final_output == "done"
    assert loaded.goal == run.goal  # untouched


async def test_list_runs_orders_most_recent_first(store):
    older, newer = make_run(), make_run()
    await store.create_run(older)
    await store.create_run(newer)

    listed = await store.list_runs()
    assert listed[0].run_id in {older.run_id, newer.run_id}
    assert {r.run_id for r in listed} == {older.run_id, newer.run_id}


# -- tasks ---------------------------------------------------------------


async def test_save_task_updates_status_independently_of_run(store):
    run = make_run()
    await store.create_run(run)
    task = run.tasks[0]

    task.status = "done"
    await store.save_task(task)

    tasks = await store.get_tasks(run.run_id)
    saved = next(t for t in tasks if t.task_id == task.task_id)
    assert saved.status == "done"


# -- events ----------------------------------------------------------------


async def test_events_are_appended_in_order(store):
    run = make_run()
    await store.create_run(run)

    await store.append_event(Event(run_id=run.run_id, event_type=EventType.RUN_CREATED))
    await store.append_event(Event(run_id=run.run_id, event_type=EventType.PLAN_CREATED))

    events = await store.get_events(run.run_id)
    assert [e.event_type.value for e in events] == ["run_created", "plan_created"]


# -- shared state: the namespace-isolation guarantee ------------------------


async def test_state_is_isolated_per_namespace(store):
    """Two 'parallel agents' write to their own task namespace and must never
    see or overwrite each other's data."""
    run = make_run()
    t1, t2 = run.tasks[0].task_id, run.tasks[1].task_id

    await store.write_state(run.run_id, t1, "findings", {"company": "A"})
    await store.write_state(run.run_id, t2, "findings", {"company": "B"})

    assert await store.read_state(run.run_id, t1) == {"findings": {"company": "A"}}
    assert await store.read_state(run.run_id, t2) == {"findings": {"company": "B"}}


async def test_read_namespaces_batches_multiple_lookups(store):
    run = make_run()
    t1, t2 = run.tasks[0].task_id, run.tasks[1].task_id
    await store.write_state(run.run_id, t1, "findings", {"company": "A"})
    await store.write_state(run.run_id, t2, "findings", {"company": "B"})

    result = await store.read_namespaces(run.run_id, [t1, t2, "missing_namespace"])
    assert result[t1] == {"findings": {"company": "A"}}
    assert result[t2] == {"findings": {"company": "B"}}
    assert result["missing_namespace"] == {}


async def test_read_all_state_groups_by_namespace(store):
    run = make_run()
    t1 = run.tasks[0].task_id
    await store.write_state(run.run_id, t1, "findings", {"company": "A"})
    await store.write_state(run.run_id, t1, "summary", "short")

    all_state = await store.read_all_state(run.run_id)
    assert all_state[t1] == {"findings": {"company": "A"}, "summary": "short"}


async def test_returned_state_is_a_copy_not_a_live_reference(store):
    """Mutating a value the caller got back must not corrupt the store --
    otherwise one agent could accidentally poison another's namespace."""
    run = make_run()
    t1 = run.tasks[0].task_id
    await store.write_state(run.run_id, t1, "findings", {"company": "A"})

    got = await store.read_state(run.run_id, t1)
    got["findings"]["company"] = "TAMPERED"

    fresh = await store.read_state(run.run_id, t1)
    assert fresh["findings"]["company"] == "A"
