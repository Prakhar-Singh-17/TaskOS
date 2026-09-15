"""MCP server exposing a single `search` tool backed by Tavily.

Runs over stdio so the agent runtime can spawn it as a subprocess and speak MCP
to it. Adding more tools later means adding another server like this one --
no changes to the core runtime.

Run standalone:  python -m taskos.mcp_servers.search_server
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from taskos.config import settings

TAVILY_ENDPOINT = "https://api.tavily.com/search"
REQUEST_TIMEOUT = 30.0

# Keep the subprocess's stderr quiet; the runtime logs tool calls itself.
logging.getLogger("mcp").setLevel(logging.WARNING)

mcp = FastMCP("taskos-search")


def _empty_response(query: str, note: str) -> dict[str, Any]:
    """Shape returned when a query legitimately finds nothing.

    This is NOT an error: the runtime classifies an empty result as a
    retryable outcome and reworks the query, which is the v1 failure demo.
    """
    return {"query": query, "answer": "", "results": [], "result_count": 0, "note": note}


def _mock_search(query: str, max_results: int) -> dict[str, Any]:
    """Deterministic offline results, for demos without a Tavily key."""
    normalized = query.strip().lower()
    if not normalized or "__no_results__" in normalized:
        return _empty_response(query, "mock: query matched the forced-empty marker")

    seed = hashlib.sha256(normalized.encode()).hexdigest()
    results = [
        {
            "title": f"[mock] Result {i + 1} for {query!r}",
            "url": f"https://example.invalid/{seed[:8]}/{i + 1}",
            "content": (
                f"Synthetic result {i + 1} about {query}. Offline mock data from "
                f"the TaskOS search MCP server; set TASKOS_SEARCH_MODE=live for real results."
            ),
            "score": round(1.0 - (i * 0.1), 2),
        }
        for i in range(min(max_results, 3))
    ]
    return {
        "query": query,
        "answer": f"[mock] Summary for {query}.",
        "results": results,
        "result_count": len(results),
        "note": "mock mode",
    }


async def _tavily_search(query: str, max_results: int, search_depth: str) -> dict[str, Any]:
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": True,
    }
    headers = {"Authorization": f"Bearer {settings.tavily_api_key}"}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(TAVILY_ENDPOINT, json=payload, headers=headers)

    if response.status_code == 401:
        raise RuntimeError("Tavily rejected the API key (401). Check TAVILY_API_KEY.")
    if response.status_code == 429:
        raise RuntimeError("Tavily rate limit hit (429).")
    response.raise_for_status()

    body = response.json()
    raw_results = body.get("results") or []
    if not raw_results:
        return _empty_response(query, "tavily returned no results")

    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
            "score": item.get("score"),
        }
        for item in raw_results
    ]
    return {
        "query": query,
        "answer": body.get("answer") or "",
        "results": results,
        "result_count": len(results),
        "note": "tavily",
    }


@mcp.tool()
async def search(query: str, max_results: int = 5, search_depth: str = "basic") -> dict[str, Any]:
    """Search the web and return ranked results.

    Args:
        query: The search query. Be specific; vague queries return nothing useful.
        max_results: Maximum number of results to return (1-10).
        search_depth: "basic" for fast lookups, "advanced" for deeper crawling.

    Returns:
        A dict with `query`, `answer`, `results` (title/url/content/score) and
        `result_count`. An empty `results` list means the search found nothing.
    """
    query = (query or "").strip()
    if not query:
        return _empty_response(query, "empty query string")

    max_results = max(1, min(int(max_results), 10))
    if search_depth not in ("basic", "advanced"):
        search_depth = "basic"

    if settings.search_mode == "mock" or not settings.tavily_api_key.strip():
        return _mock_search(query, max_results)

    return await _tavily_search(query, max_results, search_depth)


if __name__ == "__main__":
    mcp.run(transport="stdio")
