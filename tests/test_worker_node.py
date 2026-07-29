import asyncio

import pytest
from langchain_core.messages import AIMessage

from hep_multiagent.nodes.worker import execute


class FinalAnswerLLM:
    def __init__(self):
        self.messages = None
        self.tool_names = []

    def bind_tools(self, tools):
        self.tool_names = [tool.name for tool in tools]
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        if "structured_final_answer" in self.tool_names:
            return AIMessage(content="", tool_calls=[{
                "name": "structured_final_answer",
                "args": {
                    "status": "success",
                    "summary": "done",
                    "artifacts": ["result.csv"],
                    "observations": ["value=1"],
                    "limitations": [],
                },
                "id": "call-1",
            }])
        return AIMessage(content="", tool_calls=[{
            "name": "final_answer",
            "args": {"status": "success", "summary": "done"},
            "id": "call-1",
        }])


class IssueThenFinalLLM(FinalAnswerLLM):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "log_issue",
                "args": {
                    "component": "compute",
                    "problem": "needed small glue code",
                    "suggestion": "add a dedicated conversion tool",
                },
                "id": "call-1",
            }])
        return await super().ainvoke(messages)


def one_step_state():
    return {
        "current_step_id": "s1",
        "output_dir": "/tmp",
        "plan": {
            "goal": "test",
            "steps": [{
                "id": "s1",
                "name": "compute",
                "worker_type": "compute",
                "description": "compute something",
                "depends_on": [],
                "status": "running",
                "output": None,
                "solution": None,
                "artifacts": [],
                "error": None,
                "attempts": [],
            }],
        },
    }


def test_worker_can_use_plain_final_answer_when_structured_output_is_disabled():
    llm = FinalAnswerLLM()
    result = asyncio.run(execute(
        one_step_state(),
        llm,
        tools=[],
        workers={"compute": "compute prompt"},
        artifact_extensions=[".csv"],
        issue_tracking=False,
        structured_worker_output=False,
    ))

    step = result["plan"]["steps"][0]
    assert step["status"] == "completed"
    assert step["final_answer_produced"] is True
    assert step["solution"] == "success: done"


def test_worker_requires_current_step():
    state = one_step_state()
    state["current_step_id"] = "missing"

    with pytest.raises(RuntimeError, match="Current step not found"):
        asyncio.run(execute(
            state,
            FinalAnswerLLM(),
            tools=[],
            workers={"compute": "compute prompt"},
            artifact_extensions=[".csv"],
            issue_tracking=False,
        ))


def test_worker_uses_structured_completion_by_default():
    llm = FinalAnswerLLM()
    result = asyncio.run(execute(
        one_step_state(),
        llm,
        tools=[],
        workers={"compute": "compute prompt"},
        artifact_extensions=[".csv"],
        issue_tracking=False,
    ))

    step = result["plan"]["steps"][0]
    assert step["status"] == "completed"
    assert step["structured_output"]["summary"] == "done"
    assert step["structured_output"]["observations"] == ["value=1"]


def test_worker_returns_logged_issues_in_state():
    result = asyncio.run(execute(
        one_step_state(),
        IssueThenFinalLLM(),
        tools=[],
        workers={"compute": "compute prompt"},
        artifact_extensions=[".csv"],
    ))

    assert result["tool_issues"] == [
        "ISSUE_LOGGED: [compute] needed small glue code -> add a dedicated conversion tool"
    ]
