import os
from pathlib import Path
from typing import Any, Dict, List

from .mcp_env import ensure_mcp_environment, command_path

class MCPManager:
    def __init__(self):
        self._client = None
        self._tools = []
        self._tool_sources = {}
        self._session = None
        self._session_ctx = None
        self._initialized = False
        self._output_dir = None

    def uninstall(self) -> None:
        pass

    async def load(self, servers: List[Dict[str, Any]], output_dir: str = None) -> List:
        output_dir = os.path.abspath(output_dir) if output_dir else None

        if self._initialized and self._output_dir == output_dir:
            return self._tools

        if self._initialized and self._output_dir != output_dir:
            await self.close()

        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools

        base_env = {**os.environ}
        if output_dir:
            base_env["MCP_OUTPUT_DIR"] = os.path.abspath(output_dir)

        config = {}
        server_urls = {}
        for server in servers:
            if "url" not in server:
                raise ValueError("MCP server config must include 'url'")
            url = server["url"]
            name = server.get("name") or url.rstrip("/").rstrip(".git").split("/")[-1]
            try:
                env_dir, pkg = ensure_mcp_environment(name, url)
            except Exception as e:
                raise RuntimeError(f"Failed to set up MCP '{name}'. Check its url and dependencies. {e}") from e
            command_name = server.get("command", name)
            cmd = str(command_path(Path(env_dir), command_name))
            if not os.path.exists(cmd):
                fallback = str(command_path(Path(env_dir), pkg))
                cmd = fallback if os.path.exists(fallback) else command_name
            config[name] = {
                "transport": "stdio",
                "command": cmd,
                "args": server.get("args", []),
                "env": {**base_env, **server.get("env", {})},
            }
            server_urls[name] = {"url": url, "pkg": pkg}

        self._client = MultiServerMCPClient(config)
        try:
            server_name = next(iter(config))
            self._session_ctx = self._client.session(server_name)
            self._session = await self._session_ctx.__aenter__()
            self._tools = await load_mcp_tools(self._session)
            for tool in self._tools:
                srv = getattr(tool, "server_name", None) or server_name
                if srv in server_urls:
                    self._tool_sources[tool.name] = server_urls[srv]
        except Exception as e:
            raise RuntimeError(f"MCP server(s) failed to load: {e}") from e

        if not self._tools:
            raise RuntimeError("MCP server(s) loaded but no tools were found")

        self._initialized = True
        self._output_dir = output_dir
        return self._tools

    async def close(self):
        """Clean up MCP session and client resources."""
        if self._session_ctx:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_ctx = None
            self._session = None
        self._initialized = False
        self._output_dir = None

    @property
    def tools(self) -> List:
        return self._tools

    @property
    def tool_sources(self) -> Dict[str, Dict[str, str]]:
        return self._tool_sources
