"""Integration tests for the runner's retry loop: classification, capped
attempts, and query-reword recovery, all exercised through run_graph() end
to end (dispatch and prepare_retry's LLM call are the only things faked).
"""

import pytest

from taskos.agents.errors import EmptyResultError
from taskos.core import runner
from taskos.core.events import EventBus
from taskos.core.models import AgentType, FailureKind, Run, RunStatus, Task, TaskStatus
from taskos.store.memory import MemoryStore

RUN_ID = "run_test"


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


def make_run(max_attempts: int = 3) -> Run:
    task = Task(
        run_id=RUN_ID, description="deliberately unsearchable nonsense",
        assigned_agent=AgentType.RESEARCH, max_attempts=max_attempts,
    )
    return Run(run_id=RUN_ID, goal="test retry", tasks=[task])


class FlakyThenSucceeds:
    """Fails with EmptyResultError `fail_times` times, then succeeds.
    Records every query it was called with, proving reword actually changes
    what gets dispatched on the next attempt."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls_with_query: list[str] = []

    async def __call__(self, task: Task, *, tools, store) -> dict:
        self.calls_with_query.append(task.description)
        if len(self.calls_with_query) <= self.fail_times:
            raise EmptyResultError(f"no results for {task.description!r}")
        return {"summary": "found it eventually", "sources": []}


class AlwaysFails:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.call_count = 0

    async def __call__(self, task: Task, *, tools, store) -> None:
        self.call_count += 1
        raise self.exc


async def test_retries_on_empty_result_and_succeeds_within_the_cap(monkeypatch, store):
    fake_dispatch = FlakyThenSucceeds(fail_times=1)
    monkeypatch.setattr(runner, "dispatch", fake_dispatch)

    async def fake_reword_query(original: str) -> str:
        return f"reworded: {original}"

    from taskos.agents import research
    monkeypatch.setattr(research, "reword_query", fake_reword_query)

    run = make_run(max_attempts=3)
    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    task = result.tasks[0]
    assert task.status is TaskStatus.DONE
    assert task.result == {"summary": "found it eventually", "sources": []}
    assert len(task.attempts) == 2
    assert task.attempts[0].ok is False
    assert task.attempts[0].failure_kind is FailureKind.EMPTY_RESULT
    assert "reworded" in task.attempts[0].note
    assert task.attempts[1].ok is True
    assert result.status is RunStatus.COMPLETED

    # The second dispatch call actually received the reworded query --
    # the recovery mechanism changed real behavior, not just a status label.
    assert fake_dispatch.calls_with_query[0] == "deliberately unsearchable nonsense"
    assert fake_dispatch.calls_with_query[1] == "reworded: deliberately unsearchable nonsense"


async def test_exhausts_retries_and_ends_failed(monkeypatch, store):
    fake_dispatch = FlakyThenSucceeds(fail_times=99)  # never succeeds
    monkeypatch.setattr(runner, "dispatch", fake_dispatch)

    async def fake_reword_query(original: str) -> str:
        return original  # rewording doesn't help in this scenario

    from taskos.agents import research
    monkeypatch.setattr(research, "reword_query", fake_reword_query)

    run = make_run(max_attempts=3)
    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    task = result.tasks[0]
    assert task.status is TaskStatus.FAILED
    assert len(task.attempts) == 3  # capped at max_attempts, not infinite
    assert all(not a.ok for a in task.attempts)
    assert task.failure_kind is FailureKind.EMPTY_RESULT
    assert result.status is RunStatus.PARTIAL


async def test_unretryable_failure_kind_fails_after_a_single_attempt(monkeypatch, store):
    fake_dispatch = AlwaysFails(ValueError("totally unexpected bug"))
    monkeypatch.setattr(runner, "dispatch", fake_dispatch)

    run = make_run(max_attempts=3)
    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    task = result.tasks[0]
    assert task.status is TaskStatus.FAILED
    assert len(task.attempts) == 1  # UNKNOWN is not retryable -- fail fast
    assert task.attempts[0].failure_kind is FailureKind.UNKNOWN
    assert fake_dispatch.call_count == 1


async def test_survives_prepare_retry_itself_failing(monkeypatch, store):
    """If the recovery step (e.g. the reword LLM call) fails, the task should
    still retry unchanged rather than crash the whole run."""
    fake_dispatch = FlakyThenSucceeds(fail_times=1)
    monkeypatch.setattr(runner, "dispatch", fake_dispatch)

    async def broken_prepare_retry(task, failure_kind):
        raise RuntimeError("reword call hit a quota limit")

    monkeypatch.setattr(runner, "prepare_retry", broken_prepare_retry)

    run = make_run(max_attempts=3)
    result = await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    task = result.tasks[0]
    assert task.status is TaskStatus.DONE  # second attempt still ran, with the same query
    assert "retry preparation failed" in task.attempts[0].note
    assert fake_dispatch.calls_with_query[1] == fake_dispatch.calls_with_query[0]


async def test_attempt_history_is_persisted_to_the_store(monkeypatch, store):
    fake_dispatch = FlakyThenSucceeds(fail_times=1)
    monkeypatch.setattr(runner, "dispatch", fake_dispatch)

    async def fake_reword_query(original: str) -> str:
        return f"v2: {original}"

    from taskos.agents import research
    monkeypatch.setattr(research, "reword_query", fake_reword_query)

    run = make_run(max_attempts=3)
    await runner.run_graph(run, tools=None, store=store, events=EventBus(store))

    persisted = (await store.get_tasks(RUN_ID))[0]
    assert len(persisted.attempts) == 2
    assert persisted.status is TaskStatus.DONE
    assert persisted.description == "v2: deliberately unsearchable nonsense"
