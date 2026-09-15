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
