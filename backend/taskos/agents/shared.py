"""Small helpers shared by every agent that consumes another task's output.

Every agent that writes to shared state stores a dict containing a "summary"
key (Research and Synthesis also include "sources"). This is the one place
that convention is defined and read back, so a consuming agent (Writer,
Synthesis) never needs to know which agent type produced its input -- only
that it left something usable behind.
"""

from __future__ import annotations

from typing import Any


def extract_summary(namespace: dict[str, Any]) -> str | None:
    """Pull the "summary" out of whichever key a dependency wrote its output under."""
    for value in namespace.values():
        if isinstance(value, dict) and value.get("summary"):
            return value["summary"]
    return None


def extract_sources(namespace: dict[str, Any]) -> list[dict[str, str]]:
    """Pull a "sources" list out of whichever key a dependency wrote, if any."""
    for value in namespace.values():
        if isinstance(value, dict) and value.get("sources"):
            return value["sources"]
    return []


def normalize_result(result: Any) -> dict[str, Any]:
    """Turn a task's raw result -- a plain string (Writer), a
    {summary, sources} dict (Research/Synthesis), a {summary, image} dict
    (Illustrator), or a {summary, code} dict (Coder) -- into one consistent
    {"text": str, "sources": [...], "image": {...} | None, "code": {...} | None}
    envelope.

    Used to build a Run's final_output: the dashboard always renders `text`
    as markdown, `sources` as a list, `image` (when present) as a picture,
    and `code` (when present) as a code block with its output, regardless of
    which agent type happened to produce the last task in the DAG. `image`
    and `code` are fields every other agent leaves unset -- this is the
    generic-payload principle in practice: adding a new result *shape* costs
    one optional key here, not a dashboard rewrite.
    """
    if isinstance(result, dict) and result.get("summary"):
        return {
            "text": result["summary"],
            "sources": result.get("sources", []),
            "image": result.get("image"),
            "code": result.get("code"),
        }
    return {"text": "" if result is None else str(result), "sources": [], "image": None, "code": None}
