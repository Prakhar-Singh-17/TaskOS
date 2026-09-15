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

This module does not emit dashboard events yet (step 7). Dispatching a task
to its agent goes through agents/registry.py, so the runner never needs to
know what a "research" or "writer" task actually does.
"""

from __future__ import annotations

import asyncio
import logging

from taskos.agents.registry import dispatch
from taskos.config import settings
from taskos.core.graph import TaskGraph
from taskos.core.models import (
    RETRYABLE_FAILURES,
    Attempt,
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
    max_parallel_tasks: int | None = None,
) -> Run:
    """Execute every task in `run` to completion, respecting dependencies.

    Mutates and returns `run`. Each task's status/result/error is persisted
    via `store.save_task()` as soon as it changes, not just at the end, so an
    observer watching the store mid-run sees real progress.
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
            *(_run_one(task, tools=tools, store=store, semaphore=semaphore) for task in ready)
        )

    run.status = RunStatus.COMPLETED if not graph.has_failures() else RunStatus.PARTIAL
    await store.update_run(run.run_id, status=run.status.value)
    return run


async def _run_one(
    task: Task, *, tools: MCPClientManager, store: StateStore, semaphore: asyncio.Semaphore
) -> None:
    """Run a task's agent, retrying on classified, retryable failures up to
    `task.max_attempts` times. Never raises -- a failure that survives every
    retry becomes a FAILED task status, not a crashed runner."""
    async with semaphore:
        task.status = TaskStatus.RUNNING
        task.started_at = utcnow()
        await store.save_task(task)

        while True:
            attempt = Attempt(number=task.attempt_count + 1)

            try:
                result = await dispatch(task, tools=tools, store=store)
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
                break

        task.finished_at = utcnow()
        await store.save_task(task)
