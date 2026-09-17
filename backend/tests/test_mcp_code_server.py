"""Unit tests for the code MCP server's tool logic (no subprocess, no
network -- conftest.py forces TASKOS_CODE_MODE=mock for the whole suite)."""

import pytest

from taskos.mcp_servers.code_server import execute_code


async def test_mock_execution_returns_a_placeholder_without_running_anything():
    result = await execute_code("print('hello')")
    assert result["exitOk"] is True
    assert "mock mode" in result["stdout"]


async def test_empty_code_is_rejected():
    with pytest.raises(ValueError, match="code must not be empty"):
        await execute_code("   ")


async def test_unsupported_language_is_rejected():
    with pytest.raises(ValueError, match="Unsupported language"):
        await execute_code("console.log(1)", language="javascript")
