"""Manual, live smoke test for the Supervisor agent.

Not part of the pytest suite on purpose -- it makes real Gemini API calls,
so it costs quota and isn't deterministic. Run it by hand after touching the
Supervisor's prompt or parsing logic:

    python -m scripts.smoke_supervisor
"""

from __future__ import annotations

import asyncio

from taskos.agents import supervisor


async def try_goal(goal: str) -> None:
    print(f"\n=== GOAL: {goal} ===")
    run = await supervisor.plan(goal)
    for task in run.tasks:
        deps = ", ".join(task.depends_on) or "-"
        print(f"  [{task.assigned_agent.value:9s}] {task.task_id}  deps=({deps})  {task.description}")


async def main() -> None:
    await try_goal("Write a short summary of what Anthropic does")
    await try_goal("Compare the AI strategies of Google, Microsoft, and Amazon")


if __name__ == "__main__":
    asyncio.run(main())
