"""Registry of MCP servers the agent runtime connects to.

Adding a tool to TaskOS means adding an entry here plus a server module --
nothing in the agent runtime or the DAG runner changes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp import StdioServerParameters

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _stdio(module: str) -> StdioServerParameters:
    """Spawn one of our own MCP server modules with this interpreter."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        cwd=str(BACKEND_ROOT),
        env=dict(os.environ),
    )


MCP_SERVERS: dict[str, StdioServerParameters] = {
    "search": _stdio("taskos.mcp_servers.search_server"),
    "image": _stdio("taskos.mcp_servers.image_server"),
}
