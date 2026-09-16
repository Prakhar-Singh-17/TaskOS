"""MCP client layer: discovers tools from MCP servers and calls them.

Agents never import a tool function directly. They ask this manager what tools
exist (`list_tools`) and invoke them by name (`call_tool`), so the tool surface
is defined entirely by the connected MCP servers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from taskos.mcp_client.servers import MCP_SERVERS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    """A tool as advertised by an MCP server, normalized for agent/LLM use."""

    name: str
    server: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }


@dataclass
class ToolResult:
    """Outcome of a single tool call -- also the payload for the tool-call log."""

    tool: str
    server: str
    params: dict[str, Any]
    ok: bool
    duration_ms: int
    content: Any = None
    text: str = ""
    error: str | None = None

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "server": self.server,
            "params": self.params,
            "ok": self.ok,
            "durationMs": self.duration_ms,
            "result": _truncate_large_strings(self.content) if self.ok else None,
            "error": self.error,
        }


_EVENT_STRING_LIMIT = 500


def _truncate_large_strings(value: Any, limit: int = _EVENT_STRING_LIMIT) -> Any:
    """Trim any long string inside a tool result before it goes out on the
    live event feed -- generic over tool shape, not just image data: a large
    base64 blob (generate_image) or an unusually long text field from a
    future tool both get capped the same way. The *persisted* result (what
    the task actually returns/stores) is untouched; only the broadcast copy
    shrinks, since every connected dashboard receives every event."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return f"<{len(value)} chars, omitted from live event>"
    if isinstance(value, dict):
        return {k: _truncate_large_strings(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_large_strings(v, limit) for v in value]
    return value


class MCPClientManager:
    """Owns the connections to every configured MCP server.

    The MCP stdio transport builds an anyio task group per connection, and such
    a scope must be exited by the same task that entered it. So every
    connection lives inside one dedicated runner task: `start()` spins it up and
    waits until the servers are ready, `stop()` signals it to unwind. Callers
    may then invoke tools from any task.

        async with MCPClientManager() as tools:
            await tools.call_tool("search", {"query": "..."})
    """

    def __init__(self, servers: dict[str, StdioServerParameters] | None = None) -> None:
        self._servers = servers if servers is not None else MCP_SERVERS
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, ToolSpec] = {}
        self._started = False
        self._runner: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._startup_error: BaseException | None = None

    # -- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> "MCPClientManager":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.stop()

    @property
    def is_running(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            return
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._startup_error = None
        self._runner = asyncio.create_task(self._serve(), name="mcp-client-runner")

        await self._ready.wait()
        if self._startup_error is not None:
            await self._drain_runner()
            raise self._startup_error

        self._started = True
        logger.info(
            "MCP client ready: %d server(s), %d tool(s): %s",
            len(self._sessions),
            len(self._tools),
            ", ".join(sorted(self._tools)) or "none",
        )

    async def _serve(self) -> None:
        """Hold every MCP connection open until shutdown is signalled.

        Entering and exiting the exit stack both happen here, in this one task.
        """
        try:
            async with AsyncExitStack() as stack:
                try:
                    for server_name, params in self._servers.items():
                        await self._connect(stack, server_name, params)
                except BaseException as exc:  # noqa: BLE001 - reported to start()
                    self._startup_error = exc
                    return
                finally:
                    self._ready.set()

                await self._shutdown.wait()
        finally:
            self._ready.set()
            self._sessions.clear()
            self._tools.clear()

    async def _connect(
        self, stack: AsyncExitStack, server_name: str, params: StdioServerParameters
    ) -> None:
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[server_name] = session

        listing = await session.list_tools()
        for tool in listing.tools:
            if tool.name in self._tools:
                owner = self._tools[tool.name].server
                raise ValueError(
                    f"Tool name collision: '{tool.name}' exposed by both "
                    f"'{owner}' and '{server_name}'."
                )
            self._tools[tool.name] = ToolSpec(
                name=tool.name,
                server=server_name,
                description=(tool.description or "").strip(),
                input_schema=tool.inputSchema or {},
            )

    async def stop(self) -> None:
        self._started = False
        self._shutdown.set()
        await self._drain_runner()
        self._sessions.clear()
        self._tools.clear()

    async def _drain_runner(self) -> None:
        if self._runner is None:
            return
        runner, self._runner = self._runner, None
        try:
            await runner
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MCP client runner exited with an error")

    # -- discovery ---------------------------------------------------------

    def list_tools(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def describe_tools(self) -> list[dict[str, Any]]:
        """Tool catalogue in the shape handed to the LLM."""
        return [spec.to_prompt_dict() for spec in self.list_tools()]

    # -- invocation --------------------------------------------------------

    async def call_tool(self, name: str, params: dict[str, Any] | None = None) -> ToolResult:
        """Call a tool by name. Never raises for tool-level failures -- the
        outcome is reported on the ToolResult so the runtime can classify it."""
        params = params or {}
        spec = self._tools.get(name)
        started = time.perf_counter()

        if spec is None:
            available = ", ".join(sorted(self._tools)) or "none"
            return ToolResult(
                tool=name,
                server="-",
                params=params,
                ok=False,
                duration_ms=0,
                error=f"Unknown tool '{name}'. Available tools: {available}.",
            )

        session = self._sessions[spec.server]
        try:
            response = await session.call_tool(name, params)
        except Exception as exc:  # transport/protocol failure
            return ToolResult(
                tool=name,
                server=spec.server,
                params=params,
                ok=False,
                duration_ms=self._elapsed_ms(started),
                error=f"{type(exc).__name__}: {exc}",
            )

        text = "\n".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        content = response.structuredContent
        if isinstance(content, dict) and set(content.keys()) == {"result"}:
            content = content["result"]
        if content is None:
            content = text

        return ToolResult(
            tool=name,
            server=spec.server,
            params=params,
            ok=not response.isError,
            duration_ms=self._elapsed_ms(started),
            content=None if response.isError else content,
            text=text,
            error=text if response.isError else None,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
