"""DAG task runner: executes every task in a Run to completion.

Each pass asks the TaskGraph which tasks are ready (all dependencies DONE)
and runs all of them concurrently, bounded by `max_parallel_tasks`. A task
only ever waits on its own dependencies -- unrelated branches of the DAG make
progress independently, which is what makes 3 parallel Research tasks
actually run in parallel instead of one after another.

Each task attempt is classified on failure (core/retry.py) and retried up to
`task.max_attempts` times if the failure kind is retryable -- an empty search
result gets its query reworded before the next try, a malformed-output or
tool failure just retries as-is, and a failure kind outside RETRYABLE_FAILURES
(or an exhausted retry budget) marks the task FAILED immediately.

Every status transition and tool call is also emitted onto an EventBus
(core/events.py) -- that's the entire feed the dashboard renders from.
Dispatching a task to its agent goes through agents/registry.py, so the
runner never needs to know what a "research" or "writer" task actually does.
"""

from __future__ import annotations

import asyncio
import logging

from taskos.agents.registry import dispatch
from taskos.agents.shared import normalize_result
from taskos.config import settings
from taskos.core.events import EventBus, ObservedTools
from taskos.core.graph import TaskGraph
from taskos.core.models import (
    RETRYABLE_FAILURES,
    Attempt,
    Event,
    EventType,
    FailureKind,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    utcnow,
)
from taskos.core.retry import classify_failure, prepare_retry
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

logger = logging.getLogger(__name__)


async def run_graph(
    run: Run,
    *,
    tools: MCPClientManager,
    store: StateStore,
    events: EventBus,
    max_parallel_tasks: int | None = None,
) -> Run:
    """Execute every task in `run` to completion, respecting dependencies.

    Mutates and returns `run`. Each task's status/result/error is persisted
    via `store.save_task()` as soon as it changes, not just at the end, so an
    observer watching the store (or the dashboard, via `events`) mid-run sees
    real progress.
    """
    graph = TaskGraph(run.tasks)
    graph.validate()
    semaphore = asyncio.Semaphore(max_parallel_tasks or settings.max_parallel_tasks)

    while not graph.is_complete():
        newly_blocked = graph.newly_blocked_tasks()
        for task in newly_blocked:
            task.status = TaskStatus.BLOCKED
            task.failure_kind = FailureKind.DEPENDENCY_FAILED
            task.error = "One or more dependencies failed"
            await store.save_task(task)
            await events.emit(Event(
                run_id=run.run_id, task_id=task.task_id,
                agent_id=task.assigned_agent.value, event_type=EventType.TASK_BLOCKED,
                payload={"reason": task.error},
            ))

        ready = graph.ready_tasks()
        if not ready:
            if newly_blocked:
                continue  # blocking may cascade to further dependents next pass
            logger.error(
                "Scheduler stuck on run %s: graph incomplete but nothing is "
                "ready or newly blocked. This should be unreachable for a "
                "validated DAG.",
                run.run_id,
            )
            break

        await asyncio.gather(
            *(
                _run_one(task, tools=tools, store=store, events=events, semaphore=semaphore)
                for task in ready
            )
        )

    run.status = RunStatus.COMPLETED if not graph.has_failures() else RunStatus.PARTIAL
    run.finished_at = utcnow()
    run.final_output = _compute_final_output(graph)
    await store.update_run(
        run.run_id, status=run.status.value, finished_at=run.finished_at,
        final_output=run.final_output,
    )
    await events.emit(Event(
        run_id=run.run_id, event_type=EventType.RUN_COMPLETED,
        payload={"status": run.status.value, "finalOutput": run.final_output},
    ))
    return run


def _compute_final_output(graph: TaskGraph) -> dict | None:
    """The run's deliverable: whatever the DAG's terminal task(s) -- those
    with no dependents -- produced. Normally there's exactly one (the last
    Writer or Synthesis task); if a plan happens to fan out without
    converging, every successful terminal task's output is concatenated.
    None if no terminal task actually completed.
    """
    terminal_tasks = [t for t in graph.tasks if not graph.dependents_of(t.task_id)]
    done = [t for t in terminal_tasks if t.status is TaskStatus.DONE]
    if not done:
        return None
    if len(done) == 1:
        return normalize_result(done[0].result)

    normalized = [normalize_result(t.result) for t in done]
    return {
        "text": "\n\n---\n\n".join(n["text"] for n in normalized),
        "sources": [s for n in normalized for s in n["sources"]],
    }


async def _run_one(
    task: Task, *, tools: MCPClientManager, store: StateStore,
    events: EventBus, semaphore: asyncio.Semaphore,
) -> None:
    """Run a task's agent, retrying on classified, retryable failures up to
    `task.max_attempts` times. Never raises -- a failure that survives every
    retry becomes a FAILED task status, not a crashed runner."""
    observed_tools = ObservedTools(tools, events, task)

    async with semaphore:
        task.status = TaskStatus.RUNNING
        task.started_at = utcnow()
        await store.save_task(task)
        await events.emit(Event(
            run_id=task.run_id, task_id=task.task_id,
            agent_id=task.assigned_agent.value, event_type=EventType.TASK_STARTED,
            payload={"description": task.description},
        ))

        while True:
            attempt = Attempt(number=task.attempt_count + 1)

            try:
                result = await dispatch(task, tools=observed_tools, store=store)
            except Exception as exc:
                attempt.ok = False
                attempt.failure_kind = classify_failure(exc)
                attempt.error = f"{type(exc).__name__}: {exc}"
                task.failure_kind = attempt.failure_kind
                task.error = attempt.error

                will_retry = (
                    attempt.failure_kind in RETRYABLE_FAILURES
                    and attempt.number < task.max_attempts
                )
                if will_retry:
                    try:
                        attempt.note = await prepare_retry(task, attempt.failure_kind)
                    except Exception as prep_exc:
                        # The recovery step itself failed (e.g. the reword call
                        # hit a quota limit) -- degrade gracefully and retry
                        # with the task unchanged rather than crashing the run.
                        attempt.note = f"retry preparation failed ({prep_exc}); retrying unchanged"
                        logger.warning(
                            "Task %s (%s): prepare_retry failed, retrying unchanged: %s",
                            task.task_id, task.assigned_agent.value, prep_exc,
                        )
                    logger.info(
                        "Task %s (%s) attempt %d failed (%s), retrying: %s",
                        task.task_id, task.assigned_agent.value, attempt.number,
                        attempt.failure_kind.value, attempt.note or "unchanged",
                    )
                else:
                    task.status = TaskStatus.FAILED
                    logger.warning(
                        "Task %s (%s) failed permanently after %d attempt(s): %s",
                        task.task_id, task.assigned_agent.value, attempt.number, exc,
                    )

                attempt.finished_at = utcnow()
                task.attempts.append(attempt)
                await store.save_task(task)
                await events.emit(Event(
                    run_id=task.run_id, task_id=task.task_id,
                    agent_id=task.assigned_agent.value,
                    event_type=EventType.TASK_RETRYING if will_retry else EventType.TASK_FAILED,
                    payload={
                        "attempt": attempt.number, "failureKind": attempt.failure_kind.value,
                        "error": attempt.error, "note": attempt.note,
                    },
                ))
                if will_retry:
                    continue
                break
            else:
                attempt.ok = True
                attempt.finished_at = utcnow()
                task.attempts.append(attempt)
                task.status = TaskStatus.DONE
                task.result = result
                await store.save_task(task)
                await events.emit(Event(
                    run_id=task.run_id, task_id=task.task_id,
                    agent_id=task.assigned_agent.value, event_type=EventType.TASK_COMPLETED,
                    payload={"attempt": attempt.number, "result": _preview(result)},
                ))
                break

        task.finished_at = utcnow()
        await store.save_task(task)


def _preview(result: object, limit: int = 500) -> object:
    """Trim a task result for the event payload -- the full result already
    lives on the task/store; the event feed only needs enough to display."""
    text = str(result)
    return text if len(text) <= limit else text[: limit - 1] + "…"
