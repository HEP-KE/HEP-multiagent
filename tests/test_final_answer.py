from hep_multiagent.features.agent_tools import final_answer, structured_final_answer


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


def test_structured_final_answer_success():
    result = structured_final_answer.invoke({
        "status": "success",
        "summary": "Task completed",
        "artifacts": ["outputs/result.csv"],
        "observations": ["Rows counted: 10"],
        "limitations": [],
    })
    assert result["status"] == "success"
    assert result["summary"] == "Task completed"
    assert result["artifacts"] == ["outputs/result.csv"]


def test_structured_final_answer_validates_lists():
    result = structured_final_answer.invoke({
        "status": "success",
        "summary": "Task completed",
        "artifacts": "outputs/result.csv",
        "observations": [],
        "limitations": [],
    })
    assert "error" in result
