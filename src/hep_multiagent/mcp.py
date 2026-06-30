from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse


DEFAULT_TRANSPORT = "streamable_http"
REMOTE_TRANSPORTS = {"streamable_http"}


def _coerce_servers(servers: Any) -> List[Dict[str, Any]]:
    if isinstance(servers, str):
        return [{"url": servers}]
    return servers or []


def _name_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return path.rsplit("/", 1)[-1] or parsed.netloc


def build_mcp_client_config(servers: Any) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, str]]]:
    config = {}
    sources = {}

    for server in _coerce_servers(servers):
        url = server.get("url")
        if not url:
            raise ValueError("MCP server config must include 'url'")
        if not url.startswith(("http://", "https://")) or ".git" in url:
            raise ValueError("MCP server 'url' must be an HTTP endpoint")

        name = server.get("name") or _name_from_url(url)
        transport = server.get("transport", DEFAULT_TRANSPORT)
        if transport not in REMOTE_TRANSPORTS:
            raise ValueError(f"Unsupported MCP transport '{transport}' for server '{name}'")

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
        self._initialized = False

    async def load(self, servers: Any) -> List:
        if self._initialized:
            return self._tools

        from langchain_mcp_adapters.client import MultiServerMCPClient

        config, sources = build_mcp_client_config(servers)
        self._client = MultiServerMCPClient(config)
        try:
            self._tools = await self._client.get_tools()
        except Exception as e:
            raise RuntimeError(f"MCP server(s) failed to load: {e}") from e

        if not self._tools:
            raise RuntimeError("MCP server(s) loaded but no tools were found")

        for tool in self._tools:
            server_name = getattr(tool, "server_name", None)
            if server_name in sources:
                self._tool_sources[tool.name] = sources[server_name]

        self._initialized = True
        return self._tools

    async def close(self):
        self._client = None
        self._tools = []
        self._tool_sources = {}
        self._initialized = False

    @property
    def tools(self) -> List:
        return self._tools

    @property
    def tool_sources(self) -> Dict[str, Dict[str, str]]:
        return self._tool_sources
