from hep_multiagent.features.agent_tools import final_answer, structured_final_answer


def test_success():
    result = final_answer.invoke({"status": "success", "summary": "Task completed"})
    assert result == "success: Task completed"


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
    assert result["claims"] == []
    assert result["evidence"] == []


def test_structured_final_answer_accepts_claims_and_evidence():
    result = structured_final_answer.invoke({
        "status": "success",
        "summary": "Task completed",
        "artifacts": ["outputs/result.csv"],
        "observations": ["Rows counted: 10"],
        "limitations": [],
        "claims": ["The table has 10 rows."],
        "evidence": ["outputs/result.csv"],
    })
    assert result["claims"] == ["The table has 10 rows."]
    assert result["evidence"] == ["outputs/result.csv"]


def test_structured_final_answer_validates_lists():
    result = structured_final_answer.invoke({
        "status": "success",
        "summary": "Task completed",
        "artifacts": "outputs/result.csv",
        "observations": [],
        "limitations": [],
    })
    assert "error" in result
