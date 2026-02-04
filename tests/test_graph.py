from hep_multiagent.graph import _format_plan_log, _supervisor_reason, _log_lessons_recalled, _log_lesson_saved


def test_format_plan_log_basic():
    plan = {
        "goal": "Test goal",
        "steps": [
            {"id": "1", "name": "Step One", "worker_type": "data", "description": "Do something", "depends_on": []},
        ]
    }
    result = _format_plan_log(plan)
    assert "**Goal**: Test goal" in result
    assert "Step One" in result
    assert "[data]" in result


def test_format_plan_log_with_dependencies():
    plan = {
        "goal": "Goal",
        "steps": [
            {"id": "1", "name": "First", "worker_type": "data", "description": "A", "depends_on": []},
            {"id": "2", "name": "Second", "worker_type": "compute", "description": "B", "depends_on": ["1"]},
        ]
    }
    result = _format_plan_log(plan)
    assert "(depends: 1)" in result


def test_format_plan_log_truncates_description():
    plan = {
        "goal": "Goal",
        "steps": [
            {"id": "1", "name": "Step", "worker_type": "data", "description": "x" * 300, "depends_on": []},
        ]
    }
    result = _format_plan_log(plan)
    assert len(result) < 500


def test_supervisor_reason_plan_no_plan():
    result = _supervisor_reason({}, None, "plan")
    assert "No plan exists" in result


def test_supervisor_reason_plan_rejected():
    state = {"user_approved": False, "planning_feedback": "needs more detail"}
    result = _supervisor_reason(state, None, "plan")
    assert "rejected" in result
    assert "needs more detail" in result


def test_supervisor_reason_await_approval():
    result = _supervisor_reason({}, None, "await_approval")
    assert "awaiting" in result.lower()


def test_supervisor_reason_synthesize_no_plan():
    result = _supervisor_reason({}, None, "synthesize")
    assert "No plan" in result


def test_supervisor_reason_synthesize_with_stats():
    plan = {
        "steps": [
            {"status": "completed"},
            {"status": "completed"},
            {"status": "failed"},
        ]
    }
    result = _supervisor_reason({}, plan, "synthesize")
    assert "2 completed" in result
    assert "1 failed" in result


def test_supervisor_reason_execute():
    plan = {
        "steps": [
            {"name": "Ready Step", "status": "ready"},
            {"name": "Pending Step", "status": "pending"},
        ]
    }
    result = _supervisor_reason({}, plan, "execute")
    assert "Ready Step" in result
    assert "Pending Step" not in result


class MockLogger:
    def __init__(self):
        self.logs = []

    def log(self, source, message):
        self.logs.append((source, message))


def test_log_lessons_recalled_none():
    logger = MockLogger()
    _log_lessons_recalled(logger, "compute", "")
    assert len(logger.logs) == 1
    assert "Memory" in logger.logs[0][0]
    assert "No past lessons" in logger.logs[0][1]
    assert "compute" in logger.logs[0][1]


def test_log_lessons_recalled_with_lessons():
    logger = MockLogger()
    lessons = "# Lessons from Past Failures\n- Task: x\nFailed: y\n- Task: z\nFailed: w"
    _log_lessons_recalled(logger, "research", lessons)
    assert len(logger.logs) == 1
    assert "2" in logger.logs[0][1]
    assert "research" in logger.logs[0][1]


def test_log_lesson_saved():
    logger = MockLogger()
    _log_lesson_saved(logger, "viz", "Create a bar chart of galaxy masses", "File not found: data.csv")
    assert len(logger.logs) == 1
    assert "Memory" in logger.logs[0][0]
    assert "viz" in logger.logs[0][1]
    assert "bar chart" in logger.logs[0][1]
    assert "File not found" in logger.logs[0][1]
