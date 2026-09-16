"""Unit tests for the image MCP server's tool logic (no subprocess, no
network -- conftest.py forces TASKOS_IMAGE_MODE=mock for the whole suite)."""

import base64

import pytest

from taskos.mcp_servers.image_server import _mock_image, generate_image


async def test_mock_image_returns_a_valid_placeholder():
    result = await generate_image("a red panda astronaut")
    assert result["mimeType"] == "image/png"
    assert result["prompt"] == "a red panda astronaut"
    decoded = base64.b64decode(result["imageBase64"])
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n"  # real PNG signature, not garbage


async def test_empty_prompt_is_rejected():
    with pytest.raises(ValueError, match="prompt must not be empty"):
        await generate_image("   ")


async def test_dimensions_are_clamped_to_a_sane_range():
    # Mock mode ignores width/height, but the clamping happens before the
    # mode check, so this must not raise for out-of-range input either way.
    result = await generate_image("test", width=99999, height=-5)
    assert result["mimeType"] == "image/png"


def test_mock_image_is_deterministic():
    assert _mock_image("same prompt") == _mock_image("same prompt")
