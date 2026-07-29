from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient


DEFAULT_TRANSPORT = "streamable_http"
SUPPORTED_TRANSPORTS = {"streamable_http", "stdio"}


def build_mcp_client_config(servers: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    config = {}
    sources = {}

    for server in servers:
        name = server.get("name")
        if not name:
            raise ValueError("MCP server config must include 'name'")

        transport = server.get("transport", DEFAULT_TRANSPORT)
        if transport not in SUPPORTED_TRANSPORTS:
            raise ValueError(f"Unsupported MCP transport '{transport}'")

        if transport == "stdio":
            command = server.get("command")
            if not command:
                raise ValueError("MCP stdio server config must include 'command'")
            config[name] = {"transport": "stdio", "command": command, "args": server.get("args", [])}
            for key in ("env", "cwd", "encoding", "encoding_error_handler", "session_kwargs"):
                if key in server:
                    config[name][key] = server[key]
            sources[name] = {"name": name, "url": f"stdio:{command}", "transport": transport}
            continue

        url = server.get("url")
        if not url:
            raise ValueError("MCP server config must include 'url'")
        if not url.startswith(("http://", "https://")) or ".git" in url:
            raise ValueError("MCP server 'url' must be an HTTP endpoint")

        config[name] = {"transport": transport, "url": url}
        for key in ("headers", "timeout", "session_kwargs"):
            if key in server:
                config[name][key] = server[key]
        sources[name] = {"name": name, "url": url, "transport": transport}

    return config, sources


class MCPManager:
    def __init__(self):
        self._client = None
        self._tools = []
        self._tool_sources = {}

    async def load(self, servers: list[dict[str, Any]]) -> list:
        config, sources = build_mcp_client_config(servers)
        self._client = MultiServerMCPClient(config)
        try:
            self._tools = await self._client.get_tools()
        except Exception as e:
            raise RuntimeError(f"MCP server(s) failed to load: {e}") from e

        if not self._tools:
            raise RuntimeError("MCP server(s) loaded but no tools were found")

        if len(sources) == 1:
            source = next(iter(sources.values()))
            self._tool_sources = {tool.name: source for tool in self._tools}
        else:
            for tool in self._tools:
                server_name = getattr(tool, "server_name", None)
                if server_name in sources:
                    self._tool_sources[tool.name] = sources[server_name]

        return self._tools

    async def close(self):
        self._client = None
        self._tools = []
        self._tool_sources = {}

    @property
    def tools(self) -> list:
        return self._tools

    @property
    def tool_sources(self) -> dict[str, dict[str, str]]:
        return self._tool_sources
