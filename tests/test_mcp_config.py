import asyncio

import pytest

import hep_multiagent.mcp as mcp


def test_remote_url_defaults_to_streamable_http():
    config, sources = mcp.build_mcp_client_config(
        [{"name": "hep-tools", "url": "http://localhost:8000/mcp"}]
    )

    assert config == {
        "hep-tools": {
            "transport": "streamable_http",
            "url": "http://localhost:8000/mcp",
        }
    }
    assert sources == {
        "hep-tools": {
            "name": "hep-tools",
            "url": "http://localhost:8000/mcp",
            "transport": "streamable_http",
        }
    }


def test_remote_url_keeps_headers():
    config, _ = mcp.build_mcp_client_config(
        [{
            "name": "kb",
            "url": "http://localhost:8001/mcp",
            "headers": {"Authorization": "Bearer token"},
        }]
    )

    assert config["kb"] == {
        "transport": "streamable_http",
        "url": "http://localhost:8001/mcp",
        "headers": {"Authorization": "Bearer token"},
    }


def test_stdio_server_config_is_preserved():
    config, sources = mcp.build_mcp_client_config([{
        "name": "science-mcp",
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "mcp_server", "--transport", "stdio"],
        "cwd": "/tmp/project",
    }])

    assert config == {
        "science-mcp": {
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "mcp_server", "--transport", "stdio"],
            "cwd": "/tmp/project",
        }
    }
    assert sources == {
        "science-mcp": {
            "name": "science-mcp",
            "url": "stdio:python",
            "transport": "stdio",
        }
    }


def test_multiple_remote_servers_are_preserved():
    config, _ = mcp.build_mcp_client_config([
        {"name": "data", "url": "http://localhost:8000/mcp"},
        {"name": "literature", "url": "http://localhost:8001/mcp"},
    ])

    assert list(config) == ["data", "literature"]


def test_rejects_non_http_mcp_url():
    with pytest.raises(ValueError, match="HTTP endpoint"):
        mcp.build_mcp_client_config([{"name": "bad", "url": "https://example.org/mcp-server.git"}])


def test_rejects_unsupported_transport():
    with pytest.raises(ValueError, match="Unsupported MCP transport"):
        mcp.build_mcp_client_config([{
            "name": "bad",
            "url": "http://localhost:8000/mcp",
            "transport": "sse",
        }])


def test_single_server_source_applies_to_loaded_tools(monkeypatch):
    class FakeTool:
        name = "plot_sine_wave"

    class FakeClient:
        def __init__(self, config):
            self.config = config

        async def get_tools(self):
            return [FakeTool()]

    monkeypatch.setattr(mcp, "MultiServerMCPClient", FakeClient)
    manager = mcp.MCPManager()

    asyncio.run(manager.load([{
        "name": "science-mcp",
        "transport": "stdio",
        "command": "python",
    }]))

    assert manager.tool_sources == {
        "plot_sine_wave": {
            "name": "science-mcp",
            "url": "stdio:python",
            "transport": "stdio",
        }
    }
