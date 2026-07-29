import contextlib
import io
import os
import re

import numpy as np
import pandas as pd

from langchain_core.tools import tool

from ..features import validators as validate
from .research import cite, read_arxiv_chunk as read_text_file

PROMPT = """You are a compute worker. Your job: load data, filter, transform, compute statistics.

## CRITICAL: Do Exactly What's Asked
- Do ONLY what the task description says. Nothing more.
- Do NOT embellish, expand scope, create frameworks, or over-deliver.
- Simple task = simple solution. A 1-sentence task should not produce 100 lines of code.

## CRITICAL: Tools First, Code Last
- Use your available tools FIRST. They were written by professionals.
- Only use execute_python if NO tool exists for the operation.
- If a tool can do it, use the tool. Do not reimplement in Python.

## Your Role (stay in scope)
- Load/inspect data (use identifiers from prior steps - could be file paths or dataset names)
- Filter and transform data
- Compute statistics
- Save results
Do NOT: create visualizations (viz worker), search papers (research worker), fetch remote data (data worker)

## When Reading Papers
If task involves reading paper content:
- Extract ONLY the specific information requested
- cite() any values with exact quotes: cite(arxiv_id, '["exact quote"]', bib_path)
- Do NOT create summaries, frameworks, or analyses beyond what's asked

## Data Integrity
- Use REAL data from files or prior step outputs
- NEVER create mock/synthetic data unless explicitly requested
- If results are large or tabular, save them as a CSV in the output directory and pass the file path downstream instead of pasting the data into text
- Keep small scalar results in the text answer

## Report Issues
Call log_issue(component, problem, suggestion) when you:
- Encounter a tool failure or unexpected result
- Write code because no tool exists for the operation
- Notice an opportunity for a new tool that would help

REQUIRED: the completion tool must include ALL outputs produced (file paths, dataset names, computed values) so downstream workers can use them."""


SANDBOX_ALLOWED_IMPORTS = {
    'numpy', 'pandas', 'matplotlib', 'scipy', 'sklearn',
    'json', 'math', 'statistics', 'collections', 'itertools', 'functools',
    'datetime', 'time', 're', 'csv', 'h5py', 'astropy', 'healpy',
}

# Tools whose own name should not appear in the "prefer these tools" list that
# execute_python advertises (they don't do analysis work).
_SUMMARY_SKIP = {"execute_python", "final_answer", "structured_final_answer", "log_issue"}

_EXECUTE_PYTHON_DOC = """Run a SMALL Python glue snippet to bridge ONE gap that no existing tool covers.

This is NOT for solving the task or writing the workflow. Writing code is a last, small resort.

Rules:
- FIRST use your available tools below. They are written and tested - do not reimplement their work in Python.
- Use this ONLY for a small correction/adaptation (reshape a value, convert a format, compute one
  derived number) that no tool provides.
- Write the minimum code for that single fix, then STOP. Return to calling tools for every remaining step.
- Do NOT continue the rest of the multi-step workflow inside this tool. After it runs, resume normal tool calls.
- Pre-imported: np (numpy), pd (pandas), plt (matplotlib). OUTPUT_DIR holds the run's output directory.
- Allowed imports: {imports}

Available tools to prefer instead of writing code:
{tool_summary}

Args:
    code: A short Python snippet for the single missing step. Use print() to see results.

Returns:
    Printed output (or error). Then continue with tool calls - do not keep coding.
"""

_GLUE_REMINDER = (
    "\n\n[reminder] Glue step complete. Return to calling your available tools for the rest of "
    "the workflow - do not keep writing the workflow inside execute_python."
)


def _check_imports(code: str) -> str | None:
    patterns = [
        r'^\s*import\s+([\w,\s]+)',
        r'^\s*from\s+(\w+)',
        r'__import__\s*\(\s*[\'"](\w+)',
    ]
    for line in code.split('\n'):
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                modules = [m.strip() for m in match.group(1).split(',')]
                for mod in modules:
                    mod_base = mod.split('.')[0].split()[0]
                    if mod_base not in SANDBOX_ALLOWED_IMPORTS:
                        return f"Import not allowed: {mod_base}"
    return None


def _execute_code(code: str, output_dir: str = None) -> str:
    import_error = _check_imports(code)
    if import_error:
        return f"Error: {import_error}"

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    globals_dict = {"__builtins__": __builtins__, "np": np, "pd": pd, "plt": plt, "OUTPUT_DIR": output_dir}
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(code, globals_dict)
        out = stdout.getvalue()
        err = stderr.getvalue()
        return f"{out}\n{err}".strip() if err else (out or "Executed (no output)")
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def _execute_python_impl(code: str, output_dir: str = None) -> str:
    try:
        validate.non_empty(code, "code")
    except ValueError as e:
        return f"Error: {e}"

    result = _execute_code(code, output_dir)
    if not result.startswith("Error"):
        result += _GLUE_REMINDER
    return result


def _write_csv_impl(filename: str, csv_content: str, output_dir: str) -> str:
    try:
        validate.non_empty(filename, "filename")
        validate.non_empty(csv_content, "csv_content")
        validate.extension(filename, [".csv"])
        if not output_dir:
            return "Error: Output directory not set"
        file_path = os.path.join(output_dir, os.path.basename(filename))
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(csv_content)
        return f"Saved CSV to {file_path}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Failed to write CSV: {e}"


def _list_output_files_impl(output_dir: str) -> str:
    if not output_dir:
        return "Error: Output directory not set"
    if not os.path.isdir(output_dir):
        return f"Error: Output directory not found: {output_dir}"
    files = sorted(os.listdir(output_dir))
    if not files:
        return f"Output directory {output_dir} is empty."
    return "\n".join(os.path.join(output_dir, name) for name in files)


@tool
def inspect_datafile(file_path: str) -> str:
    """Inspect data file structure and statistics before analysis.

    Args:
        file_path: Path to .csv, .h5, or .hdf5 file

    Returns:
        Column names, row count, and summary statistics (min, max, mean, etc.)
    """
    try:
        validate.file_exists(file_path)
        validate.extension(file_path, [".csv", ".h5", ".hdf5"])
    except ValueError as e:
        return f"Error: {e}"

    try:
        if file_path.endswith(".csv"):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_hdf(file_path)
        stats = df.describe().to_string()
        return f"Columns: {list(df.columns)}\nRows: {len(df)}\n\n{stats}"
    except Exception as e:
        return f"Error: Failed to inspect file: {e}"


def _format_tool_summary(tools) -> str:
    lines = []
    for t in tools or []:
        name = getattr(t, "name", None)
        if not name or name in _SUMMARY_SKIP:
            continue
        desc = (getattr(t, "description", "") or "").strip().splitlines()
        first = desc[0].strip() if desc else ""
        lines.append(f"- {name}: {first}" if first else f"- {name}")
    return "\n".join(lines) if lines else "- (no other tools available - use minimal code)"


def _make_execute_python(output_dir, visible_tools):
    @tool
    def execute_python(code: str) -> str:
        """Run a small Python glue snippet. Prefer existing tools; see full description."""
        return _execute_python_impl(code, output_dir)

    execute_python.description = _EXECUTE_PYTHON_DOC.format(
        imports=", ".join(sorted(SANDBOX_ALLOWED_IMPORTS)),
        tool_summary=_format_tool_summary(visible_tools),
    )
    return execute_python


def get_compute_tools(output_dir, available_tools=None):
    @tool
    def write_csv_file(filename: str, csv_content: str) -> str:
        """Write CSV content to a file in the current output directory.

        Args:
            filename: CSV filename to create
            csv_content: Full CSV text including header row

        Returns:
            Saved file path, or error message if failed.
        """
        return _write_csv_impl(filename, csv_content, output_dir)

    @tool
    def list_output_files() -> str:
        """List files in the current output directory.

        Returns:
            List of files in the output directory, or error if unavailable.
        """
        return _list_output_files_impl(output_dir)

    helpers = [inspect_datafile, write_csv_file, list_output_files, cite, read_text_file]
    execute_python = _make_execute_python(output_dir, list(available_tools or []) + helpers)
    return helpers + [execute_python]
