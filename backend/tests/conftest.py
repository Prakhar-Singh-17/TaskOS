"""Test-wide setup.

Forces the search and image MCP servers into mock mode for the test suite,
regardless of what's configured in .env. Tests must stay deterministic and
offline -- they shouldn't depend on live search/image results (image
generation defaults to live since Pollinations is free, which makes this
override the *only* thing keeping the test suite from making real network
calls for that tool). Must be set before any `taskos` module is imported,
since MCP_SERVERS captures the environment at import time.
"""

import os

os.environ.setdefault("TASKOS_SEARCH_MODE", "mock")
os.environ.setdefault("TASKOS_IMAGE_MODE", "mock")
