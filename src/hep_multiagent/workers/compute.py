import io
import contextlib

from langchain_core.tools import tool

from ..features import validators as validate
from ..features.agent_tools import load_json, save_json
from .research import cite, read_arxiv_chunk as read_text_file

_code_approval = None


def set_code_approval(approval):
    global _code_approval
    _code_approval = approval


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
- Load/inspect data files
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

## Report Issues
Call log_issue(component, problem, suggestion) when you:
- Encounter a tool failure or unexpected result
- Write code because no tool exists for the operation
- Notice an opportunity for a new tool that would help

REQUIRED: final_answer("success", "brief result") or final_answer("failed", "reason")"""


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


def get_compute_tools():
    return [load_json, inspect_datafile, save_json, cite, read_text_file]
