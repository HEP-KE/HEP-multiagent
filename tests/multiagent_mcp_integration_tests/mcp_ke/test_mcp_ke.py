from pathlib import Path

import pytest

from helpers import live_mcp_tests_enabled, run_live_server_test


pytestmark = pytest.mark.skipif(
    not live_mcp_tests_enabled(),
    reason="Set RUN_MULTIAGENT_MCP_TESTS=1 to run live multiagent+MCP integration tests.",
)


def test_mcp_ke_multiagent_run():
    run_live_server_test(
        base_dir=Path(__file__).parent,
        server_name="mcp-ke",
        url_env="MCP_KE_SERVER_URL",
        default_url=None,
        query=(
            "Use the connected cosmology tools to load eBOSS observational data, get LCDM parameters, "
            "and summarize the available power-spectrum analysis workflow."
        ),
        skip_without_url="Set MCP_KE_SERVER_URL to a remote streamable HTTP MCP endpoint.",
    )
