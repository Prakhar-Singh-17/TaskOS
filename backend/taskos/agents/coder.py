"""Coder agent: writes a short script (Python or JavaScript -- Gemini picks
whichever fits the task, tagged on the fenced code block it returns) via
Gemini, runs it through the MCP `execute_code` tool (a sandboxed Judge0 CE
call), and self-corrects.

Unlike Research's reword-on-empty-result recovery, this agent needs no
prepare_retry() hook at all: the DAG runner already appends every failed
Attempt (with its error message) to task.attempts *before* the next call to
run() -- so the fix loop is just reading that history back on each attempt
and handing the previous error to Gemini. No new fields, no mutation of
task.description, no bespoke retry machinery.

Some goals ask for code that genuinely needs something the sandbox can't
provide (a live database/API connection, real credentials, file or network
I/O -- Judge0's sandbox is deliberately network-disabled). Retrying those
three times would just fail the same way three times, wasting quota on a
guaranteed outcome. So Gemini is asked to flag that case itself (a leading
"NOTE: ..." line) instead of us guessing from the code afterward -- when
present, this agent skips execute_code entirely and returns the draft as a
successful result with no stdout, letting the dashboard offer a manual
"run it anyway" action instead of an automatic one.
"""

from __future__ import annotations

from typing import Any

from taskos.agents.errors import CodeExecutionError, ToolCallError
from taskos.core.models import Task
from taskos.agents.llm import generate_text
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

SUPPORTED_LANGUAGES = ["python", "javascript"]

SYSTEM_INSTRUCTION = f"""You are the Coder agent of TaskOS. Given a task
description, write a single self-contained script that accomplishes it and
prints its result(s) (print() in Python, console.log() in JavaScript).

Rules:
- Choose whichever of these languages best fits the task: {", ".join(SUPPORTED_LANGUAGES)}.
  Default to Python unless the task specifically implies JavaScript/Node.js.
- The script runs headless in an isolated sandbox with NO network access, NO
  filesystem access, NO real credentials, and NO command-line input.
- If the task can be fully solved within those constraints (a computation,
  algorithm, or data transformation), write it so it prints a real,
  verifiable result -- this is the normal case.
- If the task genuinely requires something the sandbox cannot provide (a live
  database/API connection, real credentials, file or network I/O), still
  write correct, idiomatic code for it -- but first output exactly one line:
  NOTE: <one short sentence saying what this sandbox can't provide>
  before the code fence. This tells TaskOS not to attempt to run it
  automatically; the user can still choose to run it manually.
- After that optional NOTE line, output ONLY a single fenced code block
  tagged with the language, e.g. ```python or ```javascript -- no other prose.
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


def _extract_code_and_language(text: str) -> tuple[str, str, str | None]:
    """Parse Gemini's output into (code, language, unverifiable_reason).

    unverifiable_reason is None for the normal case. A leading "NOTE: ..."
    line means Gemini judged its own code unrunnable in this sandbox (needs
    network/credentials/files) -- that line becomes the reason, and the
    caller skips execute_code entirely rather than retry into a guaranteed
    failure. Falls back to "python" if the fence is missing its language tag,
    or missing entirely -- Gemini occasionally drops the fence despite being
    told to always include one; the code itself is still usable.
    """
    stripped = text.strip()

    reason = None
    lines = stripped.splitlines()
    if lines and lines[0].strip().upper().startswith("NOTE:"):
        reason = lines[0].split(":", 1)[1].strip()
        stripped = "\n".join(lines[1:]).strip()

    language = "python"
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        opening = lines[0][3:].strip().lower()
        if opening:
            language = opening
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)

    return stripped.strip(), language, reason


async def run(task: Task, *, tools: MCPClientManager, store: StateStore) -> dict[str, Any]:
    """Generate code for the task's description, execute it if plausible, and store it.

    Returns the result dict (also written to shared state under this task's
    own namespace, key "code_result"). If Gemini flagged the code as
    unverifiable here, the returned "code" has no "stdout" but a "note"
    explaining why, and this counts as a successful task -- drafting a
    correct, unexecuted script isn't a failure.

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
    code, language, unverifiable_reason = _extract_code_and_language(raw)

    if unverifiable_reason:
        code_result = {
            "summary": f"Drafted code for: {task.description}",
            "code": {"source": code, "language": language, "stdout": None, "note": unverifiable_reason},
        }
        await store.write_state(task.run_id, task.task_id, "code_result", code_result)
        return code_result

    tool_result = await tools.call_tool("execute_code", {"code": code, "language": language})
    if not tool_result.ok:
        raise ToolCallError(tool_result.error or "execute_code tool call failed")

    output = tool_result.content
    if not output.get("exitOk"):
        raise CodeExecutionError(output.get("stderr") or "code exited with an error")

    code_result = {
        "summary": f"Ran code for: {task.description}",
        "code": {"source": code, "language": language, "stdout": output.get("stdout", ""), "note": None},
    }
    await store.write_state(task.run_id, task.task_id, "code_result", code_result)
    return code_result
