"""Coder agent: writes a short Python snippet via Gemini, runs it through the
MCP `execute_code` tool (a sandboxed Judge0 CE call), and self-corrects.

Unlike Research's reword-on-empty-result recovery, this agent needs no
prepare_retry() hook at all: the DAG runner already appends every failed
Attempt (with its error message) to task.attempts *before* the next call to
run() -- so the fix loop is just reading that history back on each attempt
and handing the previous error to Gemini. No new fields, no mutation of
task.description, no bespoke retry machinery.
"""

from __future__ import annotations

from typing import Any

from taskos.agents.errors import CodeExecutionError, ToolCallError
from taskos.agents.llm import generate_text
from taskos.core.models import Task
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

SYSTEM_INSTRUCTION = """You are the Coder agent of TaskOS. Given a task
description, write a single self-contained Python 3 script that accomplishes
it and prints its result(s) with print(). The script has no return value --
whatever it prints is the only output anyone will see.

Rules:
- Output ONLY the raw Python source code. No markdown fences, no prose,
  no explanation before or after.
- The script must not read files, access the network, or accept command-line
  arguments -- it runs headless with no input unless the task says otherwise.
- Keep it short and direct: solve exactly what was asked, nothing more.
"""


def _build_prompt(description: str, prior_errors: list[str]) -> str:
    prompt = f"Task: {description}"
    if prior_errors:
        last_error = prior_errors[-1]
        prompt += (
            f"\n\nA previous attempt failed with this error:\n{last_error}\n"
            "Fix the code so it runs successfully this time."
        )
    return prompt


def _strip_code_fences(text: str) -> str:
    """Gemini sometimes wraps output in ```python ... ``` despite being told
    not to -- strip it defensively rather than fail the whole attempt over
    a formatting slip."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]  # drop the opening ```python (or bare ```) line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped.strip()


async def run(task: Task, *, tools: MCPClientManager, store: StateStore) -> dict[str, Any]:
    """Generate code for the task's description, execute it, and store it.

    Returns the result dict (also written to shared state under this task's
    own namespace, key "code_result").

    Raises ToolCallError if the sandbox call itself failed (network/tool
    transport). Raises CodeExecutionError if the sandbox ran fine but the
    generated code exited with an error -- the runner retries either kind,
    and this agent reads task.attempts on the next call to see what went
    wrong last time.
    """
    prior_errors = [a.error for a in task.attempts if not a.ok and a.error]

    raw = await generate_text(
        _build_prompt(task.description, prior_errors), system_instruction=SYSTEM_INSTRUCTION
    )
    code = _strip_code_fences(raw)

    tool_result = await tools.call_tool("execute_code", {"code": code})
    if not tool_result.ok:
        raise ToolCallError(tool_result.error or "execute_code tool call failed")

    output = tool_result.content
    if not output.get("exitOk"):
        raise CodeExecutionError(output.get("stderr") or "code exited with an error")

    code_result = {
        "summary": f"Ran code for: {task.description}",
        "code": {"source": code, "stdout": output.get("stdout", "")},
    }
    await store.write_state(task.run_id, task.task_id, "code_result", code_result)
    return code_result
