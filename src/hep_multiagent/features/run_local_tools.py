import ast
import importlib.util
import json
import re
from pathlib import Path

from langchain_core.tools import tool


ALLOWED_IMPORTS = {
    "ast",
    "collections",
    "csv",
    "datetime",
    "functools",
    "itertools",
    "json",
    "math",
    "matplotlib",
    "numpy",
    "pandas",
    "pathlib",
    "re",
    "scipy",
    "statistics",
}

_output_dir = None


def set_run_local_tools_dir(output_dir: str) -> None:
    global _output_dir
    _output_dir = output_dir


def get_run_local_tools():
    return [create_run_local_tool, run_local_tool]


def _tools_dir() -> Path:
    if not _output_dir:
        raise ValueError("Output directory is not set")
    path = Path(_output_dir) / "run_local_tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise ValueError("name must be a valid Python identifier")
    return name


def _validate_code(code: str) -> None:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif node.module:
                modules = [node.module.split(".")[0]]
            for module in modules:
                if module not in ALLOWED_IMPORTS:
                    raise ValueError(f"Import not allowed in run-local tool: {module}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec", "compile", "__import__"}:
                raise ValueError(f"Call not allowed in run-local tool: {node.func.id}")


@tool
def create_run_local_tool(name: str, code: str) -> str:
    """Create or update a run-local Python helper module.

    Use this when existing tools need small glue code for this run. The module is
    saved under the run output directory and is not added to the source repo.

    Args:
        name: Python module name for the temporary helper.
        code: Python code containing functions to call with run_local_tool.

    Returns:
        Saved helper path or validation error.
    """
    try:
        module_name = _safe_name(name)
        _validate_code(code)
        path = _tools_dir() / f"{module_name}.py"
        path.write_text(code, encoding="utf-8")
        return f"Saved run-local tool: {path}"
    except Exception as e:
        return f"Error: {e}"


@tool
def run_local_tool(name: str, function: str, arguments_json: str = "{}") -> str:
    """Run a function from a run-local helper module.

    Args:
        name: Helper module name created with create_run_local_tool.
        function: Function name to call from the helper module.
        arguments_json: JSON object of keyword arguments.

    Returns:
        Function return value or execution error.
    """
    try:
        module_name = _safe_name(name)
        function_name = _safe_name(function)
        path = _tools_dir() / f"{module_name}.py"
        if not path.exists():
            return f"Error: run-local tool not found: {module_name}"

        kwargs = json.loads(arguments_json or "{}")
        if not isinstance(kwargs, dict):
            return "Error: arguments_json must decode to a JSON object"

        spec = importlib.util.spec_from_file_location(f"run_local_tools.{module_name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, function_name, None)
        if not callable(fn):
            return f"Error: function not found in run-local tool: {function_name}"
        result = fn(**kwargs)
        return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"
