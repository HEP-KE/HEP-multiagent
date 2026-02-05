import json
from pathlib import Path

from hep_multiagent.workers import __all__ as WORKER_EXPORTS


class ExecutionNotebook:
    def __init__(self):
        self._path = None
        self._output_dir = None
        self._cells = []
        self._imports = set()
        self._pip_urls = set()
        self._tool_sources = {}
        self._logger = None

    def init(self, output_dir: str, tool_sources: dict = None, logger=None) -> None:
        self._logger = logger
        self._path = Path(output_dir) / "execution.ipynb"
        self._output_dir = str(Path(output_dir).resolve())
        self._imports = {"numpy as np", "pandas as pd", "matplotlib.pyplot as plt", "os"}
        self._pip_urls = set()
        self._tool_sources = tool_sources or {}
        self._cells = []
        self._save()

    def _format_arg(self, key: str, val) -> str:
        if isinstance(val, str) and self._output_dir and self._output_dir in val:
            path_suffix = val.replace(self._output_dir, "").lstrip("/")
            return f'{key}=os.path.join(REPLAY_DIR, {path_suffix!r})'
        return f"{key}={val!r}"

    def tool_call(self, name: str, args: dict, result: str, worker_type: str = None) -> None:
        if not self._path or result.startswith("Error:"):
            return
        if name == "execute_python":
            code = args.get("code", "")
            if self._output_dir:
                code = code.replace(self._output_dir, '" + REPLAY_DIR + "')
            source = code
        elif name in self._tool_sources:
            src = self._tool_sources[name]
            self._pip_urls.add(src["url"])
            self._imports.add(f"{src['pkg']} import {name}")
            args_str = ", ".join(self._format_arg(k, v) for k, v in args.items())
            source = f"{name}({args_str})"
        elif name in WORKER_EXPORTS:
            self._imports.add(f"hep_multiagent.workers import {name}")
            args_str = ", ".join(self._format_arg(k, v) for k, v in args.items())
            source = f"{name}({args_str})"
        else:
            if self._logger:
                self._logger.log("Hallucination", f"Unknown tool '{name}' from worker '{worker_type}'")
            args_str = ", ".join(self._format_arg(k, v) for k, v in args.items())
            source = f"# HALLUCINATED: {name}({args_str})"
        self._cells.append({
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "source": source.splitlines(keepends=True) if "\n" in source else [source],
            "outputs": []
        })
        self._save()

    def _save(self) -> None:
        cells = []
        if self._pip_urls:
            pips = "\n".join(f"!pip install -q git+{u}" for u in sorted(self._pip_urls))
            cells.append(self._cell(pips))
        if self._imports:
            imports = "\n".join(f"from {i}" if " import " in i else f"import {i}"
                               for i in sorted(self._imports))
            cells.append(self._cell(imports))
        if self._output_dir:
            setup = f'OUTPUT_DIR = {self._output_dir!r}\nREPLAY_DIR = OUTPUT_DIR + "_replay"\nos.makedirs(REPLAY_DIR, exist_ok=True)'
            cells.append(self._cell(setup))
        cells.extend(self._cells)
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
            "cells": cells
        }
        self._path.write_text(json.dumps(nb, indent=1))

    def _cell(self, source: str) -> dict:
        return {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "source": source.splitlines(keepends=True) if "\n" in source else [source],
            "outputs": []
        }

    def close(self) -> None:
        pass