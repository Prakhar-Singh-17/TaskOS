"""Top-level entry point: goal in, executed Run out.

Ties together the pieces built in steps 3-6 -- Supervisor, the state store,
the event bus, and the DAG runner -- into the one function the API layer
calls when a user submits a goal. Nothing in here is new logic; it's wiring.
"""

from __future__ import annotations

import logging

from taskos.agents import supervisor
from taskos.agents.supervisor import OutOfScopeError
from taskos.core.events import EventBus
from taskos.core.graph import TaskGraph
from taskos.core.models import Event, EventType, Run, RunStatus, utcnow
from taskos.core.runner import run_graph
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

logger = logging.getLogger(__name__)


async def execute_goal(
    goal: str,
    *,
    tools: MCPClientManager,
    store: StateStore,
    events: EventBus,
    run_id: str | None = None,
) -> Run:
    """Plan `goal` into a task DAG, persist it, run it to completion.

    Always returns a Run in a terminal status -- a failure anywhere before
    run_graph() takes over (planning, or the wiring in between) still leaves
    the run FAILED with an error message, never stuck in PLANNING forever.
    This matters because the API calls this via `asyncio.create_task()`
    (fire-and-forget): nothing else is watching for an exception here, so if
    this function doesn't record its own failure, no one ever will.

    `run_id`, if given, lets a caller (the API) know the run's id before this
    coroutine finishes -- it creates the Run row up front and returns
    immediately with the id, then runs the goal in the background.
    """
    run_kwargs = {"goal": goal, "status": RunStatus.PLANNING}
    if run_id:
        run_kwargs["run_id"] = run_id
    run = Run(**run_kwargs)
    await store.create_run(run)
    await events.emit(Event(run_id=run.run_id, event_type=EventType.RUN_CREATED, payload={"goal": goal}))

    try:
        planned = await supervisor.plan(goal)

        # Re-home the Supervisor's tasks onto the run_id already persisted above.
        for task in planned.tasks:
            task.run_id = run.run_id
        run.tasks = planned.tasks
        run.status = RunStatus.RUNNING
        for task in run.tasks:
            await store.save_task(task)
        await store.update_run(run.run_id, status=run.status.value)

        await events.emit(Event(
            run_id=run.run_id, event_type=EventType.PLAN_CREATED,
            payload={
                "tasks": [
                    {"taskId": t.task_id, "description": t.description,
                     "agent": t.assigned_agent.value, "dependsOn": t.depends_on}
                    for t in run.tasks
                ],
                "layers": TaskGraph(run.tasks).layers(),
            },
        ))

        return await run_graph(run, tools=tools, store=store, events=events)

    except OutOfScopeError as exc:
        # Not a bug -- the Supervisor correctly recognized a goal none of our
        # agents can do. No traceback, and no exception-class prefix on the
        # message: it's meant to be read as-is by the user in FinalResult.
        logger.info("Run %s rejected as out of scope: %s", run.run_id, exc)
        run.status = RunStatus.FAILED
        run.error = str(exc)
        run.finished_at = utcnow()
        await store.update_run(
            run.run_id, status=run.status.value, error=run.error, finished_at=run.finished_at
        )
        await events.emit(Event(
            run_id=run.run_id, event_type=EventType.RUN_COMPLETED,
            payload={"status": run.status.value, "error": run.error},
        ))
        return run

    except Exception as exc:
        # Covers a malformed/invalid plan, an LLM error (timeout, quota,
        # network), or any failure in the wiring above -- all of it must
        # reach a terminal status, not hang in PLANNING indefinitely.
        logger.exception("execute_goal failed for run %s", run.run_id)
        run.status = RunStatus.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = utcnow()
        await store.update_run(
            run.run_id, status=run.status.value, error=run.error, finished_at=run.finished_at
        )
        await events.emit(Event(
            run_id=run.run_id, event_type=EventType.RUN_COMPLETED,
            payload={"status": run.status.value, "error": run.error},
        ))
        return run
