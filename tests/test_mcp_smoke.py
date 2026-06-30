"""Smoke tests for a running MCP endpoint.

Set HEP_MCP_SERVER_URL before running this file.
"""

import os
import asyncio

import pytest

from hep_multiagent.mcp import MCPManager


MCP_SERVER_URL = os.environ.get("HEP_MCP_SERVER_URL")
pytestmark = pytest.mark.skipif(
    not MCP_SERVER_URL,
    reason="set HEP_MCP_SERVER_URL to a running MCP endpoint",
)


def mcp_server():
    return {"name": "hep-mcp", "url": MCP_SERVER_URL}


def test_mcp_server_loads():
    asyncio.run(_test_mcp_server_loads())


async def _test_mcp_server_loads():
    manager = MCPManager()
    try:
        await manager.load([mcp_server()])
        assert manager.tools
    finally:
        await manager.close()


def test_expected_mcp_ke_tools_are_available():
    asyncio.run(_test_expected_mcp_ke_tools_are_available())


async def _test_expected_mcp_ke_tools_are_available():
    manager = MCPManager()
    try:
        await manager.load([mcp_server()])
        tool_names = {tool.name for tool in manager.tools}
        expected = {"get_lcdm_params", "list_datasets", "load_observational_data"}
        assert expected.issubset(tool_names)
    finally:
        await manager.close()
