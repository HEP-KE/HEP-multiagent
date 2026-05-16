import os
import subprocess
import sys
from pathlib import Path


MCP_ENV_ROOT = Path.home() / ".hep-multiagent" / "mcps"


def pkg_from_url(url: str) -> str:
    return url.rstrip("/").rstrip(".git").split("/")[-1].replace("-", "_")


def env_dir_for(name: str) -> Path:
    return MCP_ENV_ROOT / name


def python_path(env_dir: Path) -> Path:
    return env_dir / "bin" / "python"


def command_path(env_dir: Path, command: str) -> Path:
    return env_dir / "bin" / command


def _source_file(env_dir: Path) -> Path:
    return env_dir / ".source-url"


def ensure_env(name: str, url: str) -> Path:
    env_dir = env_dir_for(name)
    env_dir.parent.mkdir(parents=True, exist_ok=True)
    if not python_path(env_dir).exists():
        subprocess.run([sys.executable, "-m", "venv", str(env_dir)], check=True, capture_output=True, text=True)
    source_file = _source_file(env_dir)
    if not source_file.exists():
        source_file.write_text(url)
    return env_dir


def install_mcp(env_dir: Path, url: str) -> None:
    install_url = url
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith("https://github.com"):
        install_url = url.replace("https://github.com", f"https://{token}@github.com", 1)

    target = ["-e", url] if os.path.isdir(url) else [f"git+{install_url}"]
    result = subprocess.run(
        [str(python_path(env_dir)), "-m", "pip", "install", "-q", "--disable-pip-version-check", "mcp[cli]", *target],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        label = url if os.path.isdir(url) else f"git+{url}"
        raise RuntimeError(f"pip install {label} failed:\n{result.stderr}")
    _source_file(env_dir).write_text(url)


def ensure_mcp_environment(name: str, url: str) -> tuple[str, str]:
    env_dir = ensure_env(name, url)
    source_file = _source_file(env_dir)
    if source_file.read_text().strip() != url:
        install_mcp(env_dir, url)
        return str(env_dir), pkg_from_url(url)

    pkg = pkg_from_url(url)
    default_cmd = command_path(env_dir, name)
    fallback_cmd = command_path(env_dir, pkg)
    if not default_cmd.exists() and not fallback_cmd.exists():
        install_mcp(env_dir, url)
    return str(env_dir), pkg
