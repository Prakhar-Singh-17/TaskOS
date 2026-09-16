"""Tests for the DAG task runner.

`dispatch` is faked with an instrumented async function so these tests can
prove real properties of the scheduler -- actual concurrency (via wall-clock
timing) and correct dependency ordering -- without touching Gemini, Tavily,
or a real MCP subprocess.
"""

import asyncio
import time

import pytest

from taskos.core import runner
from taskos.core.events import EventBus
from taskos.core.models import AgentType, Run, RunStatus, Task, TaskStatus
from taskos.store.memory import MemoryStore

TASK_DELAY = 0.15  # seconds; long enough to measure reliably, short enough to keep tests fast


def task(task_id: str, *, depends_on: list[str] | None = None,
         agent: AgentType = AgentType.RESEARCH) -> Task:
    return Task(
        task_id=task_id,
        run_id="run_test",
        description=f"do {task_id}",
        assigned_agent=agent,
        depends_on=depends_on or [],
    )


def fan_in_run() -> Run:
    """3 independent research tasks feeding one synthesis task -- the exact
    shape of the v1 parallel-pipeline use case."""
    tasks = [
        task("r1"), task("r2"), task("r3"),
        task("synth", depends_on=["r1", "r2", "r3"], agent=AgentType.SYNTHESIS),
    ]
    return Run(run_id="run_test", goal="compare 3 things", tasks=tasks)


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


class Instrumented:
    """Fake dispatch(): records when each task started and finished, so tests
    can assert on real overlap in wall-clock time."""

    def __init__(self, delay: float = TASK_DELAY, fail: set[str] = frozenset()) -> None:
        self.delay = delay
        self.fail = fail
        self.spans: dict[str, tuple[float, float]] = {}

    async def __call__(self, task: Task, *, tools, store) -> str:
        start = time.monotonic()
        await asyncio.sleep(self.delay)
        self.spans[task.task_id] = (start, time.monotonic())
        if task.task_id in self.fail:
            raise RuntimeError(f"{task.task_id} was told to fail")
        return f"result for {task.task_id}"


def overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


# -- concurrency -------------------------------------------------------


async def test_independent_tasks_run_concurrently_not_sequentially(monkeypatch, store):
    fake = Instrumented()
    monkeypatch.setattr(runner, "dispatch", fake)
    run = fan_in_run()

    started = time.monotonic()
    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))
    elapsed = time.monotonic() - started

    # 4 tasks at TASK_DELAY each would take ~4x as long if fully serialized;
    # with r1/r2/r3 running concurrently it should take roughly 2x (one
    # research "layer" + one synthesis "layer").
    assert elapsed < TASK_DELAY * 3
    assert overlaps(fake.spans["r1"], fake.spans["r2"])
    assert overlaps(fake.spans["r2"], fake.spans["r3"])
    assert result.status is RunStatus.COMPLETED


async def test_synthesis_does_not_start_until_all_research_tasks_finish(monkeypatch, store):
    fake = Instrumented()
    monkeypatch.setattr(runner, "dispatch", fake)
    run = fan_in_run()

    await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    research_finish_times = [fake.spans[tid][1] for tid in ("r1", "r2", "r3")]
    synth_start_time = fake.spans["synth"][0]
    assert synth_start_time >= max(research_finish_times)


async def test_concurrency_is_bounded_by_max_parallel_tasks(monkeypatch, store):
    """With only 1 slot, even 3 independent tasks must run one at a time."""
    fake = Instrumented()
    monkeypatch.setattr(runner, "dispatch", fake)
    run = fan_in_run()

    await runner.run_graph(run, tools=None, store=store, events=EventBus(store), max_parallel_tasks=1)

    assert not overlaps(fake.spans["r1"], fake.spans["r2"])
    assert not overlaps(fake.spans["r2"], fake.spans["r3"])


# -- status transitions & persistence -----------------------------------


async def test_final_output_is_the_terminal_task_result(monkeypatch, store):
    """The DAG's terminal task (no dependents) is the deliverable -- here,
    synth is the last layer, so its result becomes the run's final_output."""
    monkeypatch.setattr(runner, "dispatch", Instrumented())
    run = fan_in_run()
    await store.create_run(run)

    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    assert result.final_output == {"text": "result for synth", "sources": [], "image": None}


async def test_final_output_normalizes_a_dict_result_with_summary_and_sources(monkeypatch, store):
    async def fake_dispatch(task, *, tools, store):
        if task.task_id == "synth":
            return {"summary": "the merged findings", "sources": [{"title": "a", "url": "b"}]}
        return "irrelevant"

    monkeypatch.setattr(runner, "dispatch", fake_dispatch)
    run = fan_in_run()
    await store.create_run(run)

    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    assert result.final_output == {
        "text": "the merged findings",
        "sources": [{"title": "a", "url": "b"}],
        "image": None,
    }


async def test_final_output_is_none_when_the_terminal_task_never_completed(monkeypatch, store):
    fake = Instrumented(fail={"r1", "r2", "r3"})  # cascades to block synth entirely
    monkeypatch.setattr(runner, "dispatch", fake)
    run = fan_in_run()
    await store.create_run(run)

    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    assert result.tasks[-1].status is TaskStatus.BLOCKED
    assert result.final_output is None


async def test_all_tasks_end_up_done_and_persisted(monkeypatch, store):
    monkeypatch.setattr(runner, "dispatch", Instrumented())
    run = fan_in_run()
    await store.create_run(run)  # real usage always creates the run row first (see orchestrator.py)

    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    assert all(t.status is TaskStatus.DONE for t in result.tasks)
    assert all(t.result == f"result for {t.task_id}" for t in result.tasks)
    assert all(t.started_at is not None and t.finished_at is not None for t in result.tasks)

    # Regression check: the *run's* own finished_at was never being set --
    # only found by inspecting a real completed run's API response, where it
    # showed null despite status: completed.
    assert result.finished_at is not None
    persisted_run = await store.get_run(run.run_id)
    assert persisted_run.finished_at is not None

    persisted = await store.get_tasks(run.run_id)
    assert {t.task_id: t.status for t in persisted} == {
        t.task_id: TaskStatus.DONE for t in result.tasks
    }


# -- failure blocking ------------------------------------------------------


async def test_failed_task_blocks_its_dependents_without_running_them(monkeypatch, store):
    fake = Instrumented(fail={"r1"})
    monkeypatch.setattr(runner, "dispatch", fake)
    run = fan_in_run()

    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    by_id = {t.task_id: t for t in result.tasks}
    assert by_id["r1"].status is TaskStatus.FAILED
    assert "r1 was told to fail" in by_id["r1"].error
    assert by_id["r2"].status is TaskStatus.DONE
    assert by_id["r3"].status is TaskStatus.DONE
    assert by_id["synth"].status is TaskStatus.BLOCKED
    assert "synth" not in fake.spans  # never actually dispatched
    assert result.status is RunStatus.PARTIAL


async def test_independent_branches_are_unaffected_by_a_sibling_failure(monkeypatch, store):
    """A failure in one branch must not slow down or block an unrelated branch."""
    fake = Instrumented(fail={"r1"})
    monkeypatch.setattr(runner, "dispatch", fake)
    run = fan_in_run()

    await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    assert overlaps(fake.spans["r1"], fake.spans["r2"])  # still ran concurrently
