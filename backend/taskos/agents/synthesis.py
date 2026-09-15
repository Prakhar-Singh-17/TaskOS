"""Synthesis agent: merges findings from multiple Research tasks into one
combined summary, for a downstream Writer (or another Synthesis) to consume.

This is what turns 3 parallel research branches back into a single thread --
the fan-in point of the DAG.
"""

from __future__ import annotations

from typing import Any

from taskos.agents.errors import MissingDependencyOutputError
from taskos.agents.llm import generate_text
from taskos.agents.shared import extract_sources, extract_summary
from taskos.core.models import Task
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

SYNTHESIS_SYSTEM_INSTRUCTION = (
    "You are a synthesis agent. Merge the findings below into one coherent "
    "summary that highlights similarities, differences, and key points across "
    "all sources. Write plain prose, 4-8 sentences. Do not invent facts that "
    "aren't in the findings."
)


def _build_prompt(task_description: str, findings_by_task: dict[str, dict]) -> str:
    lines = [f"Synthesis task: {task_description}", "", "Findings to merge:"]
    for dep_task_id, namespace in findings_by_task.items():
        summary = extract_summary(namespace)
        if summary:
            lines.append(f"\nSource ({dep_task_id}):\n{summary}")
    return "\n".join(lines)


async def run(task: Task, *, tools: MCPClientManager, store: StateStore) -> dict[str, Any]:
    """Merge findings from every dependency task into one summary.

    `tools` is accepted but unused, matching the uniform agent interface (see
    agents/registry.py). Raises MissingDependencyOutputError if none of the
    dependencies left usable findings.
    """
    namespaces = await store.read_namespaces(task.run_id, task.depends_on)
    if not any(extract_summary(ns) for ns in namespaces.values()):
        raise MissingDependencyOutputError(
            f"No usable findings from dependencies: {task.depends_on}"
        )

    summary = await generate_text(
        _build_prompt(task.description, namespaces),
        system_instruction=SYNTHESIS_SYSTEM_INSTRUCTION,
    )

    merged_sources = [
        source for namespace in namespaces.values() for source in extract_sources(namespace)
    ]

    synthesis = {"summary": summary, "sources": merged_sources}
    await store.write_state(task.run_id, task.task_id, "synthesis", synthesis)
    return synthesis
