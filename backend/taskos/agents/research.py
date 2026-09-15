"""Research agent: searches the web via the MCP `search` tool and records
findings into shared state for downstream agents (Writer, Synthesis) to read.
"""

from __future__ import annotations

from typing import Any

from taskos.agents.errors import EmptyResultError, ToolCallError
from taskos.agents.llm import generate_text
from taskos.core.models import Task
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

MAX_RESULTS = 5

SUMMARY_SYSTEM_INSTRUCTION = (
    "You are a research assistant. Summarize the given search results into a "
    "concise, factual set of findings relevant to the research task. Write "
    "plain prose, 3-6 sentences. Do not invent facts that aren't in the results."
)

REWORD_SYSTEM_INSTRUCTION = (
    "You rewrite web search queries that returned zero results into a better "
    "query. Make it broader, simpler, or differently phrased -- whatever is "
    "most likely to find relevant information. Respond with ONLY the new "
    "query text, no quotes, no explanation."
)


def _build_summary_prompt(task_description: str, search_data: dict[str, Any]) -> str:
    lines = [f"Research task: {task_description}", "", "Search results:"]
    for i, result in enumerate(search_data.get("results", []), start=1):
        lines.append(f"{i}. {result.get('title', '')} ({result.get('url', '')})")
        lines.append(f"   {result.get('content', '')}")
    if search_data.get("answer"):
        lines.append(f"\nDirect answer snippet: {search_data['answer']}")
    return "\n".join(lines)


async def run(task: Task, *, tools: MCPClientManager, store: StateStore) -> dict[str, Any]:
    """Search for the task's topic, summarize the results, and store findings.

    Returns the findings dict (also written to shared state under this task's
    own namespace, key "findings", for downstream agents to read).

    Raises ToolCallError if the search tool itself failed, or EmptyResultError
    if it succeeded but found nothing -- the runner (step 6) classifies these
    into a retry strategy (retry as-is vs. reword the query).
    """
    query = task.description
    tool_result = await tools.call_tool("search", {"query": query, "max_results": MAX_RESULTS})

    if not tool_result.ok:
        raise ToolCallError(tool_result.error or "search tool call failed")

    search_data = tool_result.content
    if not search_data.get("results"):
        raise EmptyResultError(f"No search results for query: {query!r}")

    summary = await generate_text(
        _build_summary_prompt(task.description, search_data),
        system_instruction=SUMMARY_SYSTEM_INSTRUCTION,
    )

    findings = {
        "query": query,
        "summary": summary,
        "sources": [
            {"title": r.get("title", ""), "url": r.get("url", "")}
            for r in search_data.get("results", [])
        ],
    }
    await store.write_state(task.run_id, task.task_id, "findings", findings)
    return findings


async def reword_query(original_query: str) -> str:
    """Ask Gemini for a better phrasing of a query that returned nothing.

    Called by core/retry.py between attempts when a search comes back empty
    -- this is the actual "retry with reworded query" v1 failure scenario.
    """
    reworded = await generate_text(
        f"This search query returned zero results: {original_query!r}\n"
        f"Suggest a better query.",
        system_instruction=REWORD_SYSTEM_INSTRUCTION,
    )
    return reworded.strip().strip('"')
