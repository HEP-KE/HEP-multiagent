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

    def _pkg_from_url(self, url: str) -> str:
        return url.rstrip("/").rstrip(".git").split("/")[-1].replace("-", "_")

    def _install(self, url: str) -> str:
        pkg = self._pkg_from_url(url)
        install_url = url
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token and url.startswith("https://github.com"):
            install_url = url.replace("https://github.com", f"https://{token}@github.com", 1)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "mcp[cli]", f"git+{install_url}"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"pip install git+{url} failed:\n{result.stderr}")
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
        from langchain_mcp_adapters.client import MultiServerMCPClient

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
            self._tools = await self._client.get_tools()
            for tool in self._tools:
                srv = getattr(tool, "server_name", None) or next(iter(config), None)
                if srv in server_urls:
                    self._tool_sources[tool.name] = server_urls[srv]
        except Exception as e:
            raise RuntimeError(f"MCP server(s) failed to load: {e}") from e

        if not self._tools:
            raise RuntimeError("MCP server(s) loaded but no tools were found")
        return self._tools

    @property
    def tools(self) -> List:
        return self._tools

    @property
    def tool_sources(self) -> Dict[str, Dict[str, str]]:
        return self._tool_sources
