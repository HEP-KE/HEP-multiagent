from hep_multiagent.worker import (
    build_worker_prompt,
    build_worker_result,
    extract_artifacts,
    normalize_tool_result,
)


def test_build_worker_prompt_basic():
    result = build_worker_prompt("do something", "/out", [], "", [])
    assert "# Task\ndo something" in result
    assert "Save files to: /out" in result


def test_build_worker_prompt_with_artifacts():
    result = build_worker_prompt("task", "/out", ["file1.csv", "file2.json"], "", [])
    assert "# Available Files" in result
    assert "file1.csv" in result
    assert "file2.json" in result


def test_build_worker_prompt_with_context():
    result = build_worker_prompt("task", "/out", [], "prior context here", [])
    assert "# Prior Results" in result
    assert "prior context here" in result


def test_build_worker_prompt_with_previous_attempts():
    attempts = [
        {"error": "connection failed", "tool_calls": ["fetch_data"]},
        {"error": None, "tool_calls": ["query_db", "save_json"]},
    ]
    result = build_worker_prompt("task", "/out", [], "", attempts)
    assert "# Previous Attempts" in result
    assert "connection failed" in result
    assert "Try a different approach" in result


def test_build_worker_result_basic():
    result = build_worker_result([], "", [], None, [])
    assert result["output"] == ""
    assert result["solution"] == ""
    assert result["artifacts"] == []
    assert result["error"] is None


def test_build_worker_result_with_solution():
    result = build_worker_result(["[tool]: output"], "final answer", [], None, ["tool"])
    assert "[tool]: output" in result["output"]
    assert "## Answer" in result["output"]
    assert "final answer" in result["output"]
    assert result["solution"] == "final answer"


def test_build_worker_result_dedupes_artifacts():
    result = build_worker_result([], "", ["a.csv", "b.csv", "a.csv"], None, [])
    assert len(result["artifacts"]) == 2


def test_build_worker_result_attempt_truncates():
    long_output = ["x" * 2000]
    result = build_worker_result(long_output, "", [], None, [])
    assert len(result["attempt"]["output"]) <= 1000


def test_extract_artifacts_finds_files():
    text = "Saved to /path/to/data.csv and also /other/file.json"
    result = extract_artifacts(text, [".csv", ".json"])
    assert "data.csv" in result or "/path/to/data.csv" in result
    assert "file.json" in result or "/other/file.json" in result


def test_extract_artifacts_no_duplicates():
    text = "file.csv appears twice: file.csv"
    result = extract_artifacts(text, [".csv"])
    assert result.count("file.csv") == 1


def test_normalize_tool_result_none():
    assert normalize_tool_result(None) == ""


def test_normalize_tool_result_string():
    assert normalize_tool_result("hello") == "hello"


def test_normalize_tool_result_list():
    result = normalize_tool_result([{"text": "a"}, {"text": "b"}])
    assert "a" in result
    assert "b" in result


def test_normalize_tool_result_dict_text():
    assert normalize_tool_result({"type": "text", "text": "content"}) == "content"
