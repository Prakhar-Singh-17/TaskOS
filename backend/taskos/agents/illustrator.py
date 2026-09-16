"""Illustrator agent: generates an image via the MCP `generate_image` tool
and records it into shared state for downstream agents (or the dashboard's
final result) to pick up.

Same shape as every other agent -- run(task, *, tools, store) -- and the
same shared-state convention (write a dict with "summary" under this task's
own namespace) as Research/Synthesis, just with an "image" key alongside it
instead of "sources". That's what lets Writer's extract_summary() and the
runner's normalize_result() pick this up without knowing an Illustrator
task ever ran.
"""

from __future__ import annotations

from typing import Any

from taskos.agents.errors import ToolCallError
from taskos.core.models import Task
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore


async def run(task: Task, *, tools: MCPClientManager, store: StateStore) -> dict[str, Any]:
    """Generate an image for the task's description and store it.

    Returns the illustration dict (also written to shared state under this
    task's own namespace, key "illustration").

    Raises ToolCallError if the image tool itself failed -- the runner
    classifies this the same way as any other tool failure (retry as-is,
    up to the task's attempt cap).
    """
    prompt = task.description
    tool_result = await tools.call_tool("generate_image", {"prompt": prompt})

    if not tool_result.ok:
        raise ToolCallError(tool_result.error or "generate_image tool call failed")

    image_data = tool_result.content
    illustration = {
        "summary": f"Illustration: {prompt}",
        "image": {
            "base64": image_data["imageBase64"],
            "mimeType": image_data["mimeType"],
        },
    }
    await store.write_state(task.run_id, task.task_id, "illustration", illustration)
    return illustration
