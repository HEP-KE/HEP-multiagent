import io
import contextlib

from langchain_core.tools import tool

from ..features import validators as validate
from ..features.agent_tools import load_json, save_json


PROMPT = """You are a computational analysis specialist.

TOOLS: load_json, execute_python, inspect_datafile, save_json

IMPORTANT: Use save_json (NOT save_dict) to save data for other workers. save_json writes plain JSON that viz tools can read.

Your job is to perform data analysis and computations using available tools.

AVAILABLE CAPABILITIES:
- Load and inspect data files (HDF5, CSV, FITS, etc.)
- Filter and transform data
- Compute statistics and derived quantities
- Execute Python code for custom analysis

WORKFLOW:
1. Load the data file from the path provided in prior results
2. Inspect available columns/fields
3. Perform the requested analysis
4. Report results with specific values

IMPORTANT:
- Use exact column names from the data
- Include print() statements to show intermediate results
- Be quantitative: include specific numbers with units

ERROR RECOVERY:
If an operation fails:
1. State what went wrong based on the error
2. Check column names or data types
3. Retry with corrected approach

Before each action, briefly state your reasoning.

End with a clear summary of the analysis results."""


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
    def __init__(self):
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
    # Input validation
    try:
        validate.non_empty(code, "code")
    except ValueError as e:
        return str(e)

    # Tool logic
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
    return [load_json, execute_python, inspect_datafile, save_json]
