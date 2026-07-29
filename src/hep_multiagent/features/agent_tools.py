import os
from typing import Any

from langchain_core.tools import tool

from . import validators as validate


@tool
def final_answer(status: str, summary: str) -> str:
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
def structured_final_answer(
    status: str,
    summary: str,
    artifacts: Any,
    observations: Any,
    limitations: Any,
    claims: Any = None,
    evidence: Any = None,
) -> dict:
    """Call this when the task is complete and structured worker output is required.

    Args:
        status: "success" if task completed, "failed" if unable to complete
        summary: Brief plain-text summary of results or failure reason
        artifacts: File paths this worker created or used
        observations: Short factual outputs downstream agents may use
        limitations: Known failures, missing data, or uncertainty
        claims: Specific factual claims produced by this worker
        evidence: Tool call IDs, artifact paths, citation keys, or validation names supporting the claims

    Returns:
        Structured outcome for downstream synthesis.
    """
    try:
        if status not in ("success", "failed"):
            raise ValueError(f"status must be 'success' or 'failed', got: {status}")
        validate.non_empty(summary, "summary")
        if not isinstance(artifacts, list):
            raise ValueError("artifacts must be a list")
        if not isinstance(observations, list):
            raise ValueError("observations must be a list")
        if not isinstance(limitations, list):
            raise ValueError("limitations must be a list")
        claims = claims or []
        evidence = evidence or []
        if not isinstance(claims, list):
            raise ValueError("claims must be a list")
        if not isinstance(evidence, list):
            raise ValueError("evidence must be a list")
    except ValueError as e:
        return {"error": f"{e}. Retry with valid parameters."}

    return {
        "status": status,
        "summary": summary,
        "artifacts": artifacts,
        "observations": observations,
        "limitations": limitations,
        "claims": claims,
        "evidence": evidence,
    }


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
        return f"Error: {e}"

    files = sorted(os.listdir(output_dir))
    if not files:
        return f"Output directory {output_dir} is empty - no data files available."

    data_exts = {'.hdf5', '.h5', '.fits', '.csv', '.npy', '.npz', '.json', '.dat', '.txt'}
    data_files = [f for f in files if os.path.splitext(f)[1].lower() in data_exts]

    if data_files:
        return f"Data files in output directory:\n" + "\n".join(f"  - {f}" for f in data_files)
    return f"Files in output directory (no data files):\n" + "\n".join(f"  - {f}" for f in files)
