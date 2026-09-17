"""MCP server exposing a single `execute_code` tool, backed by Judge0 CE.

Runs over stdio, exactly like search_server.py and image_server.py -- the
third MCP server in the project, same shape again: adding a tool means
adding a server like this, nothing in the agent runtime changes.

Judge0 CE's public instance is free and needs no API key or signup (unlike
Tavily), so "live" can safely be the default mode. It also does the one
thing this tool must never do itself: actually run untrusted, LLM-generated
code. That execution happens in Judge0's own sandbox (isolated, no network),
not in this process -- we never spawn a subprocess or touch a Docker socket
here, on purpose. It's still a free community instance with no uptime
guarantee, so this stays swappable via TASKOS_CODE_MODE for tests/offline
demos, same as the other tools.

Run standalone:  python -m taskos.mcp_servers.code_server
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from taskos.config import settings

JUDGE0_ENDPOINT = "https://ce.judge0.com/submissions"
REQUEST_TIMEOUT = 30.0

# Python 3, the only language this tool supports for now -- one language
# keeps the prompt, the result shape, and the demo narrative simple. Add to
# this map if another language is ever needed; nothing else has to change.
LANGUAGE_IDS = {"python": 71}

# Judge0's numeric status for a clean run. Anything else (compile error,
# runtime error, time limit exceeded, ...) means the code itself failed,
# not the tool call -- checked instead of "is stderr non-empty" because a
# program can print warnings to stderr and still succeed.
_ACCEPTED_STATUS_ID = 3

logging.getLogger("mcp").setLevel(logging.WARNING)

mcp = FastMCP("taskos-code")


def _mock_execution(code: str) -> dict[str, Any]:
    return {
        "stdout": "mock mode: code was not actually executed\n",
        "stderr": "",
        "exitOk": True,
        "note": "mock mode: no real sandbox call was made",
    }


async def _judge0_execute(code: str, stdin: str, language_id: int) -> dict[str, Any]:
    payload = {"source_code": code, "language_id": language_id, "stdin": stdin}
    params = {"base64_encoded": "false", "wait": "true"}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(JUDGE0_ENDPOINT, params=params, json=payload)

    if response.status_code == 429:
        raise RuntimeError("Judge0 rate limit hit (429).")
    response.raise_for_status()

    data = response.json()
    status = data.get("status") or {}
    exit_ok = status.get("id") == _ACCEPTED_STATUS_ID
    stderr = data.get("stderr") or data.get("compile_output") or ""

    return {
        "stdout": data.get("stdout") or "",
        "stderr": stderr,
        "exitOk": exit_ok,
        "note": status.get("description", "unknown status"),
    }


@mcp.tool()
async def execute_code(code: str, stdin: str = "", language: str = "python") -> dict[str, Any]:
    """Run a short Python snippet in an isolated sandbox and return its output.

    Args:
        code: The Python source to run. Must print anything it wants
            reported back -- there is no separate return value.
        stdin: Optional input fed to the program's stdin.
        language: Only "python" is supported right now.

    Returns:
        A dict with `stdout`, `stderr`, and `exitOk` (False if the code
        raised, failed to compile, or exited non-zero -- true tool-call
        failures, like the sandbox being unreachable, raise instead of
        returning here).
    """
    code = (code or "").strip()
    if not code:
        raise ValueError("code must not be empty")

    language_id = LANGUAGE_IDS.get(language.lower())
    if language_id is None:
        raise ValueError(f"Unsupported language '{language}'. Supported: {', '.join(LANGUAGE_IDS)}")

    if settings.code_mode == "mock":
        return _mock_execution(code)

    return await _judge0_execute(code, stdin, language_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
