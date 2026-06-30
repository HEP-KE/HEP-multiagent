from pathlib import Path

from hep_multiagent.features.config import AgentFeatures
from hep_multiagent.features.diagnostics import RunDiagnostics, TokenCounter


class MockLLM:
    model = "gpt-5.5"


def _patch_token_counter(monkeypatch):
    monkeypatch.setattr(TokenCounter, "__init__", lambda self: None)
    monkeypatch.setattr(TokenCounter, "count_text", lambda self, text: len(str(text or "").split()))
    monkeypatch.setattr(TokenCounter, "count_messages", lambda self, messages: sum(self.count_text(getattr(m, "content", m)) for m in messages))


def test_diagnostics_writes_comparison_ready_json(tmp_path, monkeypatch):
    _patch_token_counter(monkeypatch)
    diagnostics = RunDiagnostics(
        query="Analyze data",
        output_dir=str(tmp_path),
        llm=MockLLM(),
        features=AgentFeatures(run_diagnostics=True, structured_worker_output=True),
        mcp_servers=[{"name": "hep-tools", "url": "http://localhost:8000/mcp"}],
    )
    diagnostics.configure_tools([], {}, ["data", "compute", "research", "viz"])
    diagnostics.event("planner", "started", "Creating execution plan")
    diagnostics.record_tool_call("compute_worker", "s1", "execute_python", "built_in", 0.1, "success", None, None, [])
    diagnostics.finalize("completed", {"final_report": "Done", "plan": {"steps": []}})

    path = Path(tmp_path) / "run_diagnostics.json"
    assert path.exists()
    content = path.read_text()
    assert '"token_count_method": "tiktoken:cl100k_base"' in content
    assert '"tool_calls_total": 1' in content


def test_diagnostics_marks_missing_artifact_as_hallucination(tmp_path, monkeypatch):
    _patch_token_counter(monkeypatch)
    diagnostics = RunDiagnostics("Make plot", str(tmp_path), MockLLM(), AgentFeatures(), None)
    result = {
        "final_report": "Done",
        "plan": {
            "steps": [
                {
                    "id": "s1",
                    "name": "plot",
                    "worker_type": "viz",
                    "status": "completed",
                    "artifacts": ["missing.png"],
                }
            ]
        },
    }

    diagnostics.finalize("completed", result)

    assert diagnostics.data["checks"]["claimed_artifacts_exist"] is False
    assert diagnostics.data["failures"][0]["type"] == "artifact_hallucination"


def test_diagnostics_flags_invalid_plan(tmp_path, monkeypatch):
    _patch_token_counter(monkeypatch)
    diagnostics = RunDiagnostics("Analyze", str(tmp_path), MockLLM(), AgentFeatures(), None)

    diagnostics.validate_plan({
        "steps": [
            {"id": "s1", "name": "bad", "worker_type": "unknown", "description": "x", "depends_on": ["missing"]}
        ]
    }, ["data", "compute"])

    assert diagnostics.data["checks"]["worker_types_valid"] is False
    assert diagnostics.data["checks"]["step_dependencies_valid"] is False
    assert diagnostics.data["failures"][0]["type"] == "agent_workflow_failure"


def test_diagnostics_marks_step_failure_recovered(tmp_path, monkeypatch):
    _patch_token_counter(monkeypatch)
    diagnostics = RunDiagnostics("Analyze", str(tmp_path), MockLLM(), AgentFeatures(), None)

    diagnostics.failure("tool_runtime_failure", "compute_worker", "s1", "tool failed", False, "tool_call_failed")
    diagnostics.mark_step_recovered("compute_worker", "s1")

    failure = diagnostics.data["failures"][0]
    assert failure["recovered"] is True
    assert failure["impact"] == "none"
    assert diagnostics.data["agents"]["compute_worker"]["recovered_failure_count"] == 1
    assert diagnostics.data["agents"]["compute_worker"]["unrecovered_failure_count"] == 0
