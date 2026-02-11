"""Smoke test for MCP tool connectivity.

Quick test to verify:
1. MCP server can be loaded
2. Tools are available
3. A simple tool call works and returns a response

Run with: pytest tests/test_mcp_smoke.py -v
"""

import asyncio
import pytest
from hep_multiagent.mcp import MCPManager


MCP_SERVER = {
    "url": "https://github.com/HEP-KE/mcp-ke.git@add-mcmc-paths",
    "name": "mcp_ke"
}


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_mcp_server_loads():
    """Test that MCP server loads and provides tools."""
    mcp = MCPManager()
    try:
        await mcp.load([MCP_SERVER])

        assert mcp.tools is not None, "No tools loaded"
        assert len(mcp.tools) > 0, "Tools list is empty"

        tool_names = [t.name for t in mcp.tools]
        print(f"\nLoaded {len(tool_names)} tools: {tool_names[:5]}...")

        # Check for expected tools
        expected = ["get_lcdm_params", "list_datasets", "load_observational_data"]
        for name in expected:
            assert name in tool_names, f"Expected tool '{name}' not found"

    finally:
        await mcp.close()
        mcp.uninstall()


@pytest.mark.asyncio
async def test_mcp_tool_call_get_params():
    """Test calling get_lcdm_params tool."""
    mcp = MCPManager()
    try:
        await mcp.load([MCP_SERVER])

        # Find the get_lcdm_params tool
        tool = next((t for t in mcp.tools if t.name == "get_lcdm_params"), None)
        assert tool is not None, "get_lcdm_params tool not found"

        # Call it
        result = await tool.ainvoke({})

        print(f"\nget_lcdm_params result: {result}")

        assert result is not None, "Tool returned None"
        assert len(str(result)) > 0, "Tool returned empty result"

    finally:
        await mcp.close()
        mcp.uninstall()


@pytest.mark.asyncio
async def test_mcp_tool_call_list_datasets():
    """Test calling list_datasets tool."""
    mcp = MCPManager()
    try:
        await mcp.load([MCP_SERVER])

        # Find the list_datasets tool
        tool = next((t for t in mcp.tools if t.name == "list_datasets"), None)
        assert tool is not None, "list_datasets tool not found"

        # Call it
        result = await tool.ainvoke({})

        print(f"\nlist_datasets result: {result}")

        assert result is not None, "Tool returned None"

    finally:
        await mcp.close()
        mcp.uninstall()


@pytest.mark.asyncio
async def test_mcp_tool_call_load_observational_data():
    """Test calling load_observational_data tool with eBOSS."""
    mcp = MCPManager()
    try:
        await mcp.load([MCP_SERVER])

        # Find the tool
        tool = next((t for t in mcp.tools if t.name == "load_observational_data"), None)
        assert tool is not None, "load_observational_data tool not found"

        # Call it (no args needed, defaults to eBOSS)
        result = await tool.ainvoke({})

        print(f"\nload_observational_data() result: {str(result)[:200]}...")

        assert result is not None, "Tool returned None"

    finally:
        await mcp.close()
        mcp.uninstall()


if __name__ == "__main__":
    # Quick manual run
    async def main():
        print("=== MCP Smoke Test ===\n")

        print("1. Loading MCP server...")
        mcp = MCPManager()
        await mcp.load([MCP_SERVER])
        print(f"   Loaded {len(mcp.tools)} tools")

        print("\n2. Calling get_lcdm_params...")
        tool = next(t for t in mcp.tools if t.name == "get_lcdm_params")
        result = await tool.ainvoke({})
        print(f"   Result: {result}")

        print("\n3. Calling list_datasets...")
        tool = next(t for t in mcp.tools if t.name == "list_datasets")
        result = await tool.ainvoke({})
        print(f"   Result: {result}")

        print("\n4. Calling load_observational_data()...")
        tool = next(t for t in mcp.tools if t.name == "load_observational_data")
        result = await tool.ainvoke({})
        print(f"   Result: {str(result)[:200]}...")

        await mcp.close()
        mcp.uninstall()

        print("\n=== All tests passed ===")

    asyncio.run(main())
