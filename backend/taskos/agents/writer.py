"""Writer agent: drafts final written output from the findings its
dependency tasks (Research or Synthesis) left in shared state.
"""

from __future__ import annotations

from typing import Any

from taskos.agents.errors import MissingDependencyOutputError
from taskos.agents.llm import generate_text
from taskos.core.models import Task
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

WRITER_SYSTEM_INSTRUCTION = (
    "You are a writer agent. Using only the findings provided, draft a clear, "
    "well-organized piece of writing that fulfills the task description. Do "
    "not invent facts that aren't in the findings."
)


def _extract_summary(namespace: dict[str, Any]) -> str | None:
    """Pull the 'summary' out of whichever key a dependency wrote.

    Research writes under the key "findings"; Synthesis (step 5) writes under
    "synthesis". Both store a dict containing "summary", so the writer doesn't
    need to know which agent type produced its input -- just that it did.
    """
    for value in namespace.values():
        if isinstance(value, dict) and value.get("summary"):
            return value["summary"]
    return None


def _build_prompt(task_description: str, findings_by_task: dict[str, dict]) -> str:
    lines = [f"Writing task: {task_description}", "", "Findings to draw on:"]
    for dep_task_id, namespace in findings_by_task.items():
        summary = _extract_summary(namespace)
        if summary:
            lines.append(f"\nSource ({dep_task_id}):\n{summary}")
    return "\n".join(lines)


async def run(task: Task, *, tools: MCPClientManager, store: StateStore) -> str:
    """Draft output from the findings of every dependency task.

    `tools` is accepted but unused -- the Writer never calls a tool directly,
    it only reads what its dependencies already wrote. Keeping the same
    signature as research.run() lets the runner dispatch to any agent
    uniformly (see agents/registry.py).

    Raises MissingDependencyOutputError if none of the dependencies left
    usable findings in shared state.
    """
    namespaces = await store.read_namespaces(task.run_id, task.depends_on)
    if not any(_extract_summary(ns) for ns in namespaces.values()):
        raise MissingDependencyOutputError(
            f"No usable findings from dependencies: {task.depends_on}"
        )

    draft = await generate_text(
        _build_prompt(task.description, namespaces),
        system_instruction=WRITER_SYSTEM_INSTRUCTION,
    )

    await store.write_state(task.run_id, task.task_id, "draft", draft)
    return draft
