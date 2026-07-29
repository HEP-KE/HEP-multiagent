from hep_multiagent.cli import mcp_servers_from_args, parse_args


def test_cli_builds_http_mcp_config():
    args = parse_args(["do work", "--mcp-url", "http://127.0.0.1:8000/mcp"])

    assert mcp_servers_from_args(args) == [{
        "name": "mcp-tools",
        "url": "http://127.0.0.1:8000/mcp",
        "transport": "streamable_http",
    }]


def test_cli_builds_stdio_mcp_config():
    args = parse_args([
        "do work",
        "--mcp-command", "python",
        "--mcp-args", "-m mcp_server --transport stdio",
    ])

    assert mcp_servers_from_args(args) == [{
        "name": "mcp-tools",
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "mcp_server", "--transport", "stdio"],
    }]
