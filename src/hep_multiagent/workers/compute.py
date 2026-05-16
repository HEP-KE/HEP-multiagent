import os
import io
import contextlib

from langchain_core.tools import tool

from ..features import validators as validate
from .research import cite, read_arxiv_chunk as read_text_file

_code_approval = None
_output_dir = None


def set_code_approval(approval):
    global _code_approval
    _code_approval = approval


def set_output_dir(output_dir):
    global _output_dir
    _output_dir = output_dir


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

REQUIRED: final_answer must include ALL outputs produced (file paths, dataset names, computed values) so downstream workers can use them."""


from ..config import SANDBOX_ALLOWED_IMPORTS


def _check_imports(code: str) -> str | None:
    import re
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


class _Sandbox:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_globals()
        return cls._instance

    def _init_globals(self):
        self.globals = {'__builtins__': __builtins__}
        try:
            import numpy as np
            import pandas as pd
            self.globals.update({'np': np, 'pd': pd})
        except ImportError:
            pass
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            self.globals.update({'plt': plt})
        except ImportError:
            pass

    def execute(self, code: str) -> str:
        import_error = _check_imports(code)
        if import_error:
            return f"Error: {import_error}"

        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exec(code, self.globals)
            out = stdout.getvalue()
            err = stderr.getvalue()
            return f"{out}\n{err}".strip() if err else (out or "Executed (no output)")
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


@tool
def execute_python(code: str) -> str:
    """Execute Python code with numpy, pandas, matplotlib pre-imported.

    Args:
        code: Python code to execute. Use print() to see results.
              Available: np (numpy), pd (pandas), plt (matplotlib.pyplot)

    Returns:
        Printed output from code execution, or error message if failed.
    """
    try:
        validate.non_empty(code, "code")
    except ValueError as e:
        return str(e)

    if _code_approval:
        response = _code_approval.request_code_approval(code)
        if not response.approved:
            return "Code execution rejected by user"

    return _Sandbox().execute(code)


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
        return str(e)

    try:
        import pandas as pd
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_hdf(file_path)
        stats = df.describe().to_string()
        return f"Columns: {list(df.columns)}\nRows: {len(df)}\n\n{stats}"
    except Exception as e:
        return f"Failed to inspect file: {e}"


@tool
def write_csv_file(filename: str, csv_content: str) -> str:
    """Write CSV content to a file in the current output directory.

    Args:
        filename: CSV filename to create
        csv_content: Full CSV text including header row

    Returns:
        Saved file path, or error message if failed.
    """
    try:
        validate.non_empty(filename, "filename")
        validate.non_empty(csv_content, "csv_content")
        validate.extension(filename, [".csv"])
        if not _output_dir:
            return "Error: Output directory not set"
        file_path = os.path.join(_output_dir, os.path.basename(filename))
        with open(file_path, "w") as f:
            f.write(csv_content)
        return f"Saved CSV to {file_path}"
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Failed to write CSV: {e}"


@tool
def list_output_files() -> str:
    """List files in the current output directory.

    Returns:
        List of files in the output directory, or error if unavailable.
    """
    if not _output_dir:
        return "Error: Output directory not set"
    if not os.path.isdir(_output_dir):
        return f"Error: Output directory not found: {_output_dir}"
    files = sorted(os.listdir(_output_dir))
    if not files:
        return f"Output directory {_output_dir} is empty."
    return "\n".join(os.path.join(_output_dir, name) for name in files)


def get_compute_tools():
    return [inspect_datafile, write_csv_file, list_output_files, cite, read_text_file]
