"""DAG task runner: executes every task in a Run to completion.

Each pass asks the TaskGraph which tasks are ready (all dependencies DONE)
and runs all of them concurrently, bounded by `max_parallel_tasks`. A task
only ever waits on its own dependencies -- unrelated branches of the DAG make
progress independently, which is what makes 3 parallel Research tasks
actually run in parallel instead of one after another.

This module only handles scheduling and status transitions. It does not retry
failed tasks (that's step 6) and does not emit dashboard events yet (step 7).
Dispatching a task to its agent goes through agents/registry.py, so the
runner never needs to know what a "research" or "writer" task actually does.
"""

from __future__ import annotations

import asyncio
import logging

from taskos.agents.registry import dispatch
from taskos.config import settings
from taskos.core.graph import TaskGraph
from taskos.core.models import Run, RunStatus, Task, TaskStatus, utcnow
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
    """Run a single task's agent and record the outcome. Never raises --
    an agent failure becomes a FAILED task status, not a crashed runner."""
    async with semaphore:
        task.status = TaskStatus.RUNNING
        task.started_at = utcnow()
        await store.save_task(task)

        try:
            result = await dispatch(task, tools=tools, store=store)
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = f"{type(exc).__name__}: {exc}"
            logger.warning("Task %s (%s) failed: %s", task.task_id, task.assigned_agent.value, exc)
        else:
            task.status = TaskStatus.DONE
            task.result = result

        task.finished_at = utcnow()
        await store.save_task(task)
