from hep_multiagent.features.run_record import RunRecord, RunRecorder, validate_run


def test_run_record_captures_tool_artifact_and_step(tmp_path):
    artifact = tmp_path / "points.csv"
    artifact.write_text("x,y,label\n1,2,a\n3,,b\nnan,4,c\n")

    step = {
        "id": "s1",
        "name": "plot_points",
        "worker_type": "compute",
        "status": "completed",
        "error": None,
        "artifacts": [str(artifact)],
        "attempts": [{"tool_calls": ["plot_random_points"], "output": "ok", "error": None}],
    }

    recorder = RunRecorder()
    recorder.start("plot 30 points", str(tmp_path), [{"name": "science", "url": "http://127.0.0.1:8000/mcp"}])
    recorder.tool_call(step, "plot_random_points", {"n": 30}, f"Saved {artifact}", [str(artifact)])
    recorder.finish({"plan": {"steps": [step]}})

    record = RunRecord.model_validate_json((tmp_path / "run.json").read_text())

    assert record.status == "completed"
    assert record.tool_calls[0].tool_name == "plot_random_points"
    assert record.tool_calls[0].args == {"n": 30}
    assert record.tool_calls[0].artifacts[0].exists is True
    assert record.tool_calls[0].artifacts[0].sha256
    summary = record.tool_calls[0].artifacts[0].summary
    assert summary["rows"] == 3
    assert summary["columns"] == ["x", "y", "label"]
    assert summary["column_stats"]["x"]["finite_count"] == 2
    assert summary["column_stats"]["x"]["non_finite"] == 1
    assert summary["column_stats"]["x"]["mean"] == 2.0
    assert summary["column_stats"]["y"]["missing"] == 1
    assert summary["column_stats"]["label"]["non_numeric"] == 3
    assert record.steps[0].tool_calls == [record.tool_calls[0].id]
    assert all(validation.passed for validation in record.validations)


def test_run_record_marks_failed_state(tmp_path):
    recorder = RunRecorder()
    recorder.start("run failing query", str(tmp_path))
    recorder.finish({"error": "planner failed"})

    record = RunRecord.model_validate_json((tmp_path / "run.json").read_text())

    assert record.status == "failed"
    assert record.error == "planner failed"
    assert record.validations[-1].name == "run_status_matches_steps"
    assert record.validations[-1].passed is True


def test_run_record_captures_logged_issues(tmp_path):
    recorder = RunRecorder()
    recorder.start("query", str(tmp_path))
    recorder.finish({"tool_issues": ["ISSUE_LOGGED: [compute] problem -> suggestion"]})

    record = RunRecord.model_validate_json((tmp_path / "run.json").read_text())

    assert record.issues == ["ISSUE_LOGGED: [compute] problem -> suggestion"]


def test_run_record_redacts_mcp_secrets(tmp_path):
    recorder = RunRecorder()
    recorder.start(
        "query",
        str(tmp_path),
        [{
            "name": "kb",
            "url": "http://127.0.0.1:8000/mcp",
            "headers": {"Authorization": "Bearer token", "X-Trace": "run-1"},
            "env": {"ARGO_USER": "scientist", "API_KEY": "secret"},
        }],
    )

    record = RunRecord.model_validate_json((tmp_path / "run.json").read_text())

    server = record.mcp_servers[0]
    assert server["url"] == "http://127.0.0.1:8000/mcp"
    assert server["headers"]["Authorization"] == "<redacted>"
    assert server["headers"]["X-Trace"] == "run-1"
    assert server["env"]["ARGO_USER"] == "scientist"
    assert server["env"]["API_KEY"] == "<redacted>"


def test_validate_run_flags_missing_artifacts(tmp_path):
    recorder = RunRecorder()
    recorder.start("query", str(tmp_path))
    recorder.finish({
        "plan": {
            "steps": [{
                "id": "s1",
                "name": "missing_file",
                "worker_type": "compute",
                "status": "completed",
                "error": None,
                "artifacts": [str(tmp_path / "missing.csv")],
                "attempts": [{"tool_calls": ["write_csv_file"]}],
            }]
        }
    })

    record = RunRecord.model_validate_json((tmp_path / "run.json").read_text())

    artifact_check = next(validation for validation in record.validations if validation.name == "artifacts_exist_and_are_hashed")
    assert artifact_check.passed is False
    assert "missing.csv" in artifact_check.details


def test_validate_run_flags_tool_call_without_step(tmp_path):
    recorder = RunRecorder()
    recorder.start("query", str(tmp_path))
    step = {"id": "missing", "name": "x", "worker_type": "compute"}
    recorder.tool_call(step, "tool", {}, "ok", [])

    record = RunRecord.model_validate(recorder.record)
    validations = validate_run(record)

    tool_check = next(validation for validation in validations if validation.name == "tool_calls_reference_steps")
    assert tool_check.passed is False
    assert "missing" in tool_check.details


def test_run_record_captures_tool_source_and_python_code(tmp_path):
    recorder = RunRecorder()
    recorder.start("query", str(tmp_path))
    step = {"id": "s1", "name": "glue", "worker_type": "compute"}
    recorder.tool_call(
        step,
        "execute_python",
        {"code": "print(1 + 1)"},
        "2",
        [],
        {"name": "science", "url": "stdio:python", "transport": "stdio"},
    )

    record = RunRecord.model_validate(recorder.record)

    assert record.tool_calls[0].id == "tc1"
    assert record.tool_calls[0].code == "print(1 + 1)"
    assert record.tool_calls[0].source == {
        "name": "science",
        "url": "stdio:python",
        "transport": "stdio",
    }


def test_run_record_captures_environment_and_tool_schema(tmp_path):
    class Tool:
        name = "plot_random_points"
        description = "Plot points."
        args_schema = {
            "properties": {
                "n": {"type": "integer"},
                "api_key": {"type": "string"},
            }
        }

    recorder = RunRecorder()
    recorder.start("query", str(tmp_path), tools=[Tool()])

    record = RunRecord.model_validate_json((tmp_path / "run.json").read_text())

    assert record.environment["python"]
    assert record.environment["platform"]
    assert record.tools[0]["name"] == "plot_random_points"
    assert record.tools[0]["args_schema"]["properties"]["api_key"] == {"type": "string"}


def test_run_record_redacts_tool_call_secret_args(tmp_path):
    recorder = RunRecorder()
    recorder.start("query", str(tmp_path))
    step = {"id": "s1", "name": "call", "worker_type": "data"}
    recorder.tool_call(step, "fetch_data", {"api_key": "secret", "dataset": "public"}, "ok", [])

    record = RunRecord.model_validate(recorder.record)

    assert record.tool_calls[0].args == {"api_key": "<redacted>", "dataset": "public"}


def test_run_record_summarizes_png_artifact(tmp_path):
    png = tmp_path / "plot.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x02"
        b"\x00\x00\x00\x03"
        b"\x08\x02\x00\x00\x00"
        b"\x00\x00\x00\x00"
    )

    recorder = RunRecorder()
    recorder.start("query", str(tmp_path))
    artifact = recorder.artifact(str(png))

    assert artifact.summary == {"type": "png", "width": 2, "height": 3}


def test_run_record_captures_citation_evidence(tmp_path):
    (tmp_path / "references.bib").write_text("""@article{arxiv230100774,
  title = {Test Paper},
  author = {A. Author},
  year = {2023},
  eprint = {2301.00774},
  note = {["quoted source text"]}
}
""")

    recorder = RunRecorder()
    recorder.start("query", str(tmp_path))
    recorder.finish({"plan": {"steps": []}})

    record = RunRecord.model_validate_json((tmp_path / "run.json").read_text())

    assert record.citations[0].key == "arxiv230100774"
    assert record.citations[0].arxiv_id == "2301.00774"
    assert record.citations[0].quotes == ["quoted source text"]
    citation_check = next(validation for validation in record.validations if validation.name == "citations_have_source_quotes")
    assert citation_check.passed is True


def test_run_record_captures_claims_with_evidence(tmp_path):
    recorder = RunRecorder()
    recorder.start("query", str(tmp_path))
    step = {"id": "s1", "name": "final", "worker_type": "compute"}
    recorder.tool_call(
        step,
        "structured_final_answer",
        {
            "status": "success",
            "summary": "done",
            "artifacts": [],
            "observations": [],
            "limitations": [],
            "claims": ["The CSV has 30 rows."],
            "evidence": ["outputs/points.csv"],
        },
        "success: done",
        [],
    )
    recorder.finish({"plan": {"steps": []}})

    record = RunRecord.model_validate_json((tmp_path / "run.json").read_text())

    assert record.claims[0].claim == "The CSV has 30 rows."
    assert record.claims[0].evidence == ["outputs/points.csv"]
    claim_check = next(validation for validation in record.validations if validation.name == "claims_have_evidence")
    assert claim_check.passed is True
