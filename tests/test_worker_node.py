import asyncio

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


def test_worker_completes_with_final_answer():
    llm = FinalAnswerLLM()
    result = asyncio.run(execute(
        one_step_state(),
        llm,
        tools=[],
        workers={"compute": "compute prompt"},
        artifact_extensions=[".csv"],
        default_output_dir="/tmp",
        issue_tracking=False,
    ))

    step = result["plan"]["steps"][0]
    assert step["status"] == "completed"
    assert step["final_answer_produced"] is True
    assert step["solution"] == "success: done"


def test_structured_worker_output_is_recorded():
    llm = FinalAnswerLLM()
    result = asyncio.run(execute(
        one_step_state(),
        llm,
        tools=[],
        workers={"compute": "compute prompt"},
        artifact_extensions=[".csv"],
        default_output_dir="/tmp",
        issue_tracking=False,
        structured_worker_output=True,
    ))

    step = result["plan"]["steps"][0]
    assert step["status"] == "completed"
    assert step["structured_output"]["summary"] == "done"
    assert step["structured_output"]["observations"] == ["value=1"]


def test_role_prompts_can_be_disabled():
    llm = FinalAnswerLLM()
    asyncio.run(execute(
        one_step_state(),
        llm,
        tools=[],
        workers={"compute": "verbose compute prompt"},
        artifact_extensions=[".csv"],
        default_output_dir="/tmp",
        issue_tracking=False,
        role_prompts=False,
    ))

    assert llm.messages[0].content == "You are the compute worker."
