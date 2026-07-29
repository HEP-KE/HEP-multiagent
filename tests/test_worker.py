from hep_multiagent.worker import build_worker_prompt, extract_artifacts, normalize_tool_result


def test_worker_prompt_includes_context_needed_for_retry():
    prompt = build_worker_prompt(
        "task",
        "/out",
        ["file1.csv"],
        "prior context",
        [{"output": "", "error": "connection failed", "tool_calls": ["fetch_data"]}],
    )

    assert "Save files to: /out" in prompt
    assert "file1.csv" in prompt
    assert "prior context" in prompt
    assert "connection failed" in prompt


def test_artifact_extraction_deduplicates_paths():
    result = extract_artifacts("Saved file.csv and /tmp/file.csv", [".csv"])

    assert sorted(result) == ["/tmp/file.csv", "file.csv"]


def test_normalize_mcp_text_results():
    result = normalize_tool_result([{"text": "a"}, {"text": "b"}])

    assert result == "a\nb"
