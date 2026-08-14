import pytest

from helpers import live_mcp_tests_enabled, run_live_server_test


pytestmark = pytest.mark.skipif(
    not live_mcp_tests_enabled(),
    reason="Set RUN_MULTIAGENT_MCP_TESTS=1 to run live multiagent+MCP integration tests.",
)


def test_mcp_microlensing_multiagent_run(tmp_path):
    run_live_server_test(
        base_dir=tmp_path,
        server_name="mcp-microlensing",
        url_env="MCP_MICROLENSING_SERVER_URL",
        default_url=None,
        query=(
            "Use the connected microlensing tools to create or inspect a small microlensing analysis. "
            "Summarize what the tools did and include any generated artifact paths the tools returned."
        ),
        skip_without_url="Set MCP_MICROLENSING_SERVER_URL to a remote streamable HTTP MCP endpoint.",
    )
