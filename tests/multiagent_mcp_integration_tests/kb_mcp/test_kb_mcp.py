from pathlib import Path

import pytest

from helpers import live_mcp_tests_enabled, run_live_server_test


pytestmark = pytest.mark.skipif(
    not live_mcp_tests_enabled(),
    reason="Set RUN_MULTIAGENT_MCP_TESTS=1 to run live multiagent+MCP integration tests.",
)


def test_kb_mcp_multiagent_run():
    run_live_server_test(
        base_dir=Path(__file__).parent,
        server_name="kb-mcp",
        url_env="KB_MCP_SERVER_URL",
        default_url=None,
        query=(
            "Search the connected knowledge base for Mu2e detector design. "
            "Summarize the most relevant matching documents and identify which MCP tools were used."
        ),
        skip_without_url="Set KB_MCP_SERVER_URL to a remote streamable HTTP MCP endpoint.",
    )
