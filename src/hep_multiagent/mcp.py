import os
import subprocess
import sys
from typing import Any, Dict, List


class MCPManager:
    def __init__(self):
        self._client = None
        self._tools = []
        self._tool_sources = {}
        self._installed_pkgs = []
        self._session = None
        self._session_ctx = None
        self._initialized = False
        self._output_dir = None

    def _pkg_from_url(self, url: str) -> str:
        return url.rstrip("/").rstrip(".git").split("/")[-1].replace("-", "_")

    def _install(self, url: str) -> str:
        pkg = self._pkg_from_url(url)
        if os.path.isdir(url):
            # Local path: install in editable mode for development
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "mcp[cli]", "-e", url],
                capture_output=True, text=True
            )
            label = url
        else:
            # Remote URL: install from git
            install_url = url
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if token and url.startswith("https://github.com"):
                install_url = url.replace("https://github.com", f"https://{token}@github.com", 1)
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "mcp[cli]", f"git+{install_url}"],
                capture_output=True, text=True
            )
            label = f"git+{url}"
        if result.returncode != 0:
            raise RuntimeError(f"pip install {label} failed:\n{result.stderr}")
        self._installed_pkgs.append(pkg)
        return pkg

    def uninstall(self) -> None:
        for pkg in self._installed_pkgs:
            subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", pkg],
                capture_output=True, text=True
            )
        self._installed_pkgs = []

    async def load(self, servers: List[Dict[str, Any]], output_dir: str = None) -> List:
        output_dir = os.path.abspath(output_dir) if output_dir else None

        # If already initialized with same output_dir, return cached tools
        if self._initialized and self._output_dir == output_dir:
            return self._tools

        # If output_dir changed, close existing session first
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
            pkg = self._install(url)
            name = server.get("name", pkg)
            venv_bin = os.path.join(sys.prefix, "bin", name)
            cmd = venv_bin if os.path.exists(venv_bin) else name
            config[name] = {
                "transport": "stdio",
                "command": cmd,
                "args": server.get("args", []),
                "env": {**base_env, **server.get("env", {})},
            }
            server_urls[name] = {"url": url, "pkg": pkg}

        self._client = MultiServerMCPClient(config)
        try:
            # Use persistent session for tool calls to share state
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
