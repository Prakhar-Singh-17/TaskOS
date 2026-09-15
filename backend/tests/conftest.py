"""Test-wide setup.

Forces the search MCP server into mock mode for the test suite, regardless of
whether a real TAVILY_API_KEY is configured in .env. Tests must stay
deterministic and offline -- they shouldn't depend on live search results or
burn API quota every time they run. Must be set before any `taskos` module is
imported, since MCP_SERVERS captures the environment at import time.
"""

import os

os.environ.setdefault("TASKOS_SEARCH_MODE", "mock")
