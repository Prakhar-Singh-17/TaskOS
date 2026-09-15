"""Manual, live smoke test for the parallel Research -> Synthesis pipeline.

Proves v1's use case #2 ("parallel pipeline: 3 parallel Research agents ->
Synthesis agent, proves DAG concurrency + shared state merge") end-to-end
against real services, using the actual DAG runner (not a hand-rolled loop).

Not part of the pytest suite -- real API calls, real wall-clock timing.

    python -m scripts.smoke_parallel
"""

from __future__ import annotations

import asyncio
import time

from taskos.agents import supervisor
from taskos.core.runner import run_graph
from taskos.mcp_client.client import MCPClientManager
from taskos.store.memory import MemoryStore


async def main() -> None:
    goal = "Compare the AI strategies of Google, Microsoft, and Amazon"
    print(f"GOAL: {goal}\n")

    run = await supervisor.plan(goal)
    print("PLAN:")
    for task in run.tasks:
        print(f"  [{task.assigned_agent.value:9s}] {task.task_id}  deps={task.depends_on}")

    store = MemoryStore()
    await store.connect()
    await store.create_run(run)

    print("\nRunning DAG...")
    started = time.monotonic()
    async with MCPClientManager() as tools:
        result = await run_graph(run, tools=tools, store=store)
    elapsed = time.monotonic() - started

    print(f"\nDone in {elapsed:.1f}s -- status: {result.status.value}")
    print("\nPER-TASK TIMING (overlap here is the proof of real concurrency):")
    for t in result.tasks:
        started = t.started_at.isoformat() if t.started_at else "never ran (blocked)"
        duration = f"{t.duration_ms}ms" if t.duration_ms is not None else "-"
        print(f"  {t.task_id:16s} [{t.assigned_agent.value:9s}] {t.status.value:8s} "
              f"{duration:>8s}  started_at={started}")
        if t.status.value == "failed":
            print(f"      error: {t.error}")

    synth = next((t for t in result.tasks if t.assigned_agent.value == "synthesis"), None)
    if synth and synth.status.value == "done":
        print("\n=== SYNTHESIS OUTPUT ===")
        print(synth.result["summary"])
    else:
        print("\n(synthesis did not complete -- see task statuses above)")

    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
