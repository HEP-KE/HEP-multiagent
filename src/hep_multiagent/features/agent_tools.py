import os
from typing import Literal

from langchain_core.tools import tool

from . import validators as validate


@tool
def final_answer(status: Literal["success", "failed"], summary: str) -> str:
    """Call this when the task is complete. Stops execution and reports outcome.

    Args:
        status: "success" if task completed, "failed" if unable to complete
        summary: Brief plain-text summary of results or failure reason (no markdown)

    Returns:
        Confirmation of recorded outcome.
    """
    try:
        if status not in ("success", "failed"):
            raise ValueError(f"status must be 'success' or 'failed', got: {status}")
        validate.non_empty(summary, "summary")
    except ValueError as e:
        return f"Error: {e}. Retry with valid parameters."

    return f"{status}: {summary}"


@tool
def list_output_files(output_dir: str) -> str:
    """List files in the output directory only. Use this to see what data is available.

    Args:
        output_dir: The output directory path (provided in task description)

    Returns:
        List of files in the output directory, or error if not found.
    """
    try:
        validate.dir_exists(output_dir)
    except ValueError as e:
        return str(e)

    files = sorted(os.listdir(output_dir))
    if not files:
        return f"Output directory {output_dir} is empty - no data files available."

    data_exts = {'.hdf5', '.h5', '.fits', '.csv', '.npy', '.npz', '.json', '.dat', '.txt'}
    data_files = [f for f in files if os.path.splitext(f)[1].lower() in data_exts]

    if data_files:
        return f"Data files in output directory:\n" + "\n".join(f"  - {f}" for f in data_files)
    return f"Files in output directory (no data files):\n" + "\n".join(f"  - {f}" for f in files)
