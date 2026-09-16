"""MCP server exposing a single `generate_image` tool, backed by Pollinations.ai.

Runs over stdio, exactly like search_server.py -- this is the second MCP
server in the project, and deliberately follows that one's shape closely to
prove the point: adding a tool means adding a server like this, nothing in
the agent runtime changes.

Pollinations is free and needs no API key or signup (unlike Tavily), so
"live" can safely be the default mode -- there's no cost or credential gate
behind it. It's still a third-party service with no uptime guarantee, so
this stays swappable via TASKOS_IMAGE_MODE for tests/offline demos.

Run standalone:  python -m taskos.mcp_servers.image_server
"""

from __future__ import annotations

import base64
import logging
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

from taskos.config import settings

POLLINATIONS_ENDPOINT = "https://image.pollinations.ai/prompt/{prompt}"
REQUEST_TIMEOUT = 30.0

# A tiny 1x1 transparent PNG -- deterministic mock output, clearly not a real
# generated image, so a demo running offline is obviously distinguishable
# from one hitting the real service.
_MOCK_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

logging.getLogger("mcp").setLevel(logging.WARNING)

mcp = FastMCP("taskos-image")


def _mock_image(prompt: str) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "mimeType": "image/png",
        "imageBase64": _MOCK_PNG_BASE64,
        "note": "mock mode: 1x1 placeholder pixel, not a real generated image",
    }


async def _pollinations_image(prompt: str, width: int, height: int, seed: int | None) -> dict[str, Any]:
    url = POLLINATIONS_ENDPOINT.format(prompt=quote(prompt))
    params: dict[str, Any] = {"width": width, "height": height, "nologo": "true"}
    if seed is not None:
        params["seed"] = seed

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(url, params=params, follow_redirects=True)

    if response.status_code == 429:
        raise RuntimeError("Pollinations rate limit hit (429).")
    response.raise_for_status()

    mime_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    return {
        "prompt": prompt,
        "mimeType": mime_type,
        "imageBase64": base64.b64encode(response.content).decode("ascii"),
        "note": "pollinations",
    }


@mcp.tool()
async def generate_image(
    prompt: str, width: int = 1024, height: int = 1024, seed: int | None = None
) -> dict[str, Any]:
    """Generate an image from a text prompt.

    Args:
        prompt: What to draw. Be descriptive -- style, subject, composition.
        width: Image width in pixels (default 1024).
        height: Image height in pixels (default 1024).
        seed: Optional seed for reproducible output; omit for a random image
            each call.

    Returns:
        A dict with `prompt`, `mimeType`, and `imageBase64` (the image bytes,
        base64-encoded so they travel cleanly over MCP's JSON-RPC transport).
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt must not be empty")

    width = max(64, min(int(width), 2048))
    height = max(64, min(int(height), 2048))

    if settings.image_mode == "mock":
        return _mock_image(prompt)

    return await _pollinations_image(prompt, width, height, seed)


if __name__ == "__main__":
    mcp.run(transport="stdio")
