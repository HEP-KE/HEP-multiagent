"""Tests for final_answer tool and outcome parsing."""

from hep_multiagent.features.agent_tools import final_answer


def test_success():
    result = final_answer.invoke({"status": "success", "summary": "Task completed"})
    assert result == "success: Task completed"


def test_failed():
    result = final_answer.invoke({"status": "failed", "summary": "Could not find data"})
    assert result == "failed: Could not find data"


def test_empty_summary_returns_error():
    result = final_answer.invoke({"status": "success", "summary": ""})
    assert "Error:" in result
    assert "Retry" in result


def test_invalid_status_returns_error():
    result = final_answer.invoke({"status": "unknown", "summary": "test"})
    assert "Error:" in result
    assert "Retry" in result


def test_outcome_parsing():
    """Test that nodes/worker.py correctly parses final_answer output."""
    def check_outcome(solution):
        solution_lower = (solution or "").lower()
        has_success = solution_lower.startswith("success:")
        has_failure = solution_lower.startswith("failed:")
        return has_success, has_failure

    assert check_outcome("success: done") == (True, False)
    assert check_outcome("failed: error") == (False, True)
    assert check_outcome("other text") == (False, False)
    assert check_outcome("") == (False, False)
    assert check_outcome(None) == (False, False)
