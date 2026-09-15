"""Manual, live smoke test for the failure + recovery scenario.

Proves v1's use case #3 ("forced bad search query -> retry -> recovery,
visible in the attempt history") end-to-end. Forces the search MCP server's
own empty-result marker so the task's first attempt is guaranteed to fail
with EmptyResultError; the runner classifies that as EMPTY_RESULT, calls
research.reword_query() (one real Gemini call) to get a sensible query, and
retries -- the second attempt uses mock search results (deterministic, free)
and succeeds.

Search stays in mock mode on purpose: deterministic and free. Only the
reword step and the findings-summary step cost a real Gemini call.

    python -m scripts.smoke_failure
"""

from __future__ import annotations

import os

os.environ["TASKOS_SEARCH_MODE"] = "mock"  # must be set before any taskos import

import asyncio  # noqa: E402

from taskos.core.models import AgentType, Run, Task  # noqa: E402
from taskos.core.runner import run_graph  # noqa: E402
from taskos.mcp_client.client import MCPClientManager  # noqa: E402
from taskos.store.memory import MemoryStore  # noqa: E402


async def main() -> None:
    task = Task(
        run_id="demo_run",
        description="__no_results__ this query is deliberately unsearchable nonsense",
        assigned_agent=AgentType.RESEARCH,
        max_attempts=3,
    )
    run = Run(run_id="demo_run", goal="Prove the failure-recovery scenario", tasks=[task])
    print(f"INITIAL QUERY: {task.description!r}\n")

    store = MemoryStore()
    await store.connect()
    await store.create_run(run)

    async with MCPClientManager() as tools:
        result = await run_graph(run, tools=tools, store=store)

    finished = result.tasks[0]
    print(f"FINAL STATUS: {finished.status.value}")
    print(f"ATTEMPTS MADE: {len(finished.attempts)} (cap was {finished.max_attempts})\n")
    for a in finished.attempts:
        outcome = "OK" if a.ok else f"FAILED ({a.failure_kind.value})"
        print(f"  attempt {a.number}: {outcome}")
        if a.note:
            print(f"    -> {a.note}")

    print(f"\nFINAL QUERY USED: {finished.description!r}")
    if finished.status.value == "done":
        print(f"\nFINDINGS SUMMARY:\n{finished.result['summary']}")

    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
