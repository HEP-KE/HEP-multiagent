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


def test_string_server_shorthand_uses_remote_endpoint():
    config, _ = mcp.build_mcp_client_config("http://localhost:8000/mcp")

    assert config["mcp"] == {
        "transport": "streamable_http",
        "url": "http://localhost:8000/mcp",
    }


def test_multiple_remote_servers_are_preserved():
    config, _ = mcp.build_mcp_client_config([
        {"name": "data", "url": "http://localhost:8000/mcp"},
        {"name": "literature", "url": "http://localhost:8001/mcp"},
    ])

    assert list(config) == ["data", "literature"]


def test_rejects_non_http_mcp_url():
    with pytest.raises(ValueError, match="HTTP endpoint"):
        mcp.build_mcp_client_config([{"url": "https://example.org/mcp-server.git"}])


def test_rejects_unsupported_transport():
    with pytest.raises(ValueError, match="Unsupported MCP transport"):
        mcp.build_mcp_client_config([{
            "name": "bad",
            "url": "http://localhost:8000/mcp",
            "transport": "sse",
        }])
