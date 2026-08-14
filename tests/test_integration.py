"""Integration test simulating a complete agent run."""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from hep_multiagent import Agent, AgentFeatures
from hep_multiagent.features.agent_trace import MarkdownLogger
from hep_multiagent.features.citation_builder import BibTeXManager
from hep_multiagent.features.replay_notebook import ExecutionNotebook
from hep_multiagent.features.report_generator import LaTeXReport
from hep_multiagent.features.session_resume import SQLiteCheckpoint
from hep_multiagent.graph import build_graph
from hep_multiagent.nodes import planner
from hep_multiagent.nodes.planner import PlanOutput, validate_plan_data
from hep_multiagent.nodes.router import route
from hep_multiagent.nodes.supervisor import route_action, supervise
from hep_multiagent.workers.compute import get_compute_tools


def make_mock_tool(name: str, response: str):
    tool = MagicMock()
    tool.name = name
    tool.description = f"Mock {name} tool"
    tool.args_schema = None
    tool.invoke = MagicMock(return_value=response)
    tool.ainvoke = AsyncMock(return_value=response)
    return tool


def make_execute_python_tool(output_dir=None):
    return next(
        tool for tool in get_compute_tools(output_dir)
        if tool.name == "execute_python"
    )


class MockLLM:
    def __init__(self):
        self.call_count = 0
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def with_structured_output(self, schema):
        return MockStructuredLLM(schema)

    def _make_response(self, messages):
        self.call_count += 1
        content = str(messages[-1].content) if messages else ""
        system_content = str(messages[0].content) if messages else ""

        if "data acquisition" in system_content.lower() or "what data sources" in content.lower():
            return AIMessage(content="Available data sources: arxiv papers, simulation data.")
        elif "research" in content.lower() or "search" in content.lower():
            return AIMessage(content="Found 3 relevant papers on dark matter detection.")
        elif "compute" in content.lower() or "analyze" in content.lower():
            return AIMessage(content="Analysis complete. Results saved.")
        else:
            return AIMessage(content=r"\section{Answer}\nTest completed successfully.")

    async def ainvoke(self, messages):
        return self._make_response(messages)

    def invoke(self, messages):
        return self._make_response(messages)


class MockStructuredLLM:
    def __init__(self, schema):
        self.schema = schema

    async def ainvoke(self, messages):
        return self.schema(
            goal="Test query execution",
            steps=[
                {
                    "id": "s1",
                    "name": "search_papers",
                    "worker_type": "research",
                    "description": "Search for papers on the topic",
                    "depends_on": [],
                },
                {
                    "id": "s2",
                    "name": "analyze_results",
                    "worker_type": "compute",
                    "description": "Analyze the search results",
                    "depends_on": ["s1"],
                },
            ],
        )


@pytest.fixture
def temp_output_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_tools():
    return [
        make_mock_tool("search_arxiv", '[{"arxiv_id": "2301.00001", "title": "Test Paper"}]'),
        make_mock_tool("get_data", '{"values": [1, 2, 3]}'),
        make_mock_tool("save_file", "Saved: /tmp/test.json"),
    ]


def test_agent_feature_toggles_disable_optional_components():
    llm = MockLLM()
    features = AgentFeatures(
        report=False,
        citations=False,
        execution_log=False,
        replay_notebook=False,
        issue_tracking=False,
    )
    agent = Agent(llm=llm, mcp_servers=None, features=features)

    assert agent.features == features
    assert agent.report is None
    assert agent.references is None
    assert agent.logger is None
    assert agent.notebook is None


def test_agent_resume_requires_existing_checkpoint(temp_output_dir):
    llm = MockLLM()
    features = AgentFeatures(report=False, citations=False, execution_log=False, replay_notebook=False)
    agent = Agent(llm=llm, mcp_servers=None, features=features)
    agent.checkpoint = SQLiteCheckpoint(os.path.join(temp_output_dir, "checkpoint.db"))

    with pytest.raises(RuntimeError, match="No checkpoint found"):
        asyncio.run(agent.run("resume this query", output_dir=temp_output_dir, resume=True))


def test_planner_consultations_can_be_disabled(monkeypatch):
    class PlanOnlyLLM:
        def with_structured_output(self, schema):
            self.schema = schema
            return self

        async def ainvoke(self, messages):
            return self.schema(
                goal="answer research query",
                steps=[{
                    "id": "s1",
                    "name": "search",
                    "worker_type": "research",
                    "description": "search papers",
                    "depends_on": [],
                }],
            )

    async def fail_consult(*args, **kwargs):
        raise AssertionError("consultant should not be called")

    monkeypatch.setattr(planner.CONSULTANTS["arxiv"], "consult", fail_consult)
    state = {"messages": [HumanMessage(content="Find interesting papers")], "output_dir": "/tmp"}
    result = asyncio.run(planner.plan(
        state,
        PlanOnlyLLM(),
        tools=[],
        worker_docs="- research: Search arxiv and cite papers",
        planner_consultations=False,
        worker_types=("research",),
    ))

    assert result["plan"]["steps"][0]["worker_type"] == "research"


def test_logger_writes_to_file(temp_output_dir):
    logger = MarkdownLogger()
    logger.init(temp_output_dir)

    logger.log("Test", "Test content")
    logger.thought("Thinking about the problem...")
    logger.tool_call("test_tool", {"arg": "value"}, "result")
    logger.close()

    log_path = os.path.join(temp_output_dir, "execution_log.md")
    assert os.path.exists(log_path)

    with open(log_path) as f:
        content = f.read()

    assert "Test content" in content
    assert "Thinking about" in content
    assert "test_tool" in content


def test_notebook_writes_to_file(temp_output_dir):
    notebook = ExecutionNotebook()
    notebook.init(temp_output_dir, {})
    notebook.tool_call("execute_python", {"code": "print('hello')"}, "hello", "compute")

    nb_path = os.path.join(temp_output_dir, "execution.ipynb")
    assert os.path.exists(nb_path)

    with open(nb_path) as f:
        nb = json.load(f)

    assert nb["nbformat"] == 4
    assert len(nb["cells"]) > 0


def test_full_workflow_mock(temp_output_dir, mock_tools):
    async def run_workflow():
        llm = MockLLM()
        logger = MarkdownLogger()
        logger.init(temp_output_dir)
        notebook = ExecutionNotebook()
        notebook.init(temp_output_dir, {})
        report = LaTeXReport()
        references = BibTeXManager()
        checkpointer = MemorySaver()

        graph = build_graph(
            llm=llm,
            tools=mock_tools,
            report_writer=report,
            references=references,
            artifact_extensions=[".json", ".png", ".pdf"],
            checkpointer=checkpointer,
            logger=logger,
            notebook=notebook,
        )

        initial_state = {
            "messages": [HumanMessage(content="Test query about dark matter")],
            "next_action": "plan",
            "output_dir": temp_output_dir,
        }

        config = {"configurable": {"thread_id": "test-thread"}}
        result = await graph.ainvoke(initial_state, config)

        assert result is not None
        assert "plan" in result or "final_report" in result

        logger.close()
        log_path = os.path.join(temp_output_dir, "execution_log.md")
        assert os.path.exists(log_path)

        with open(log_path) as f:
            log_content = f.read()

        assert "Supervisor" in log_content or "Planner" in log_content

    asyncio.run(run_workflow())


def test_execute_python_basic():
    execute_python = make_execute_python_tool()

    result = execute_python.invoke({"code": "print(2 + 2)"})
    assert "4" in result

    result = execute_python.invoke({"code": "import numpy as np; print(np.mean([1,2,3]))"})
    assert "2.0" in result


def test_execute_python_blocks_os():
    execute_python = make_execute_python_tool()

    result = execute_python.invoke({"code": "import os"})
    assert "Import not allowed: os" in result

    result = execute_python.invoke({"code": "import subprocess"})
    assert "Import not allowed: subprocess" in result


def test_execute_python_blocks_network():
    execute_python = make_execute_python_tool()

    result = execute_python.invoke({"code": "import socket"})
    assert "Import not allowed: socket" in result

    result = execute_python.invoke({"code": "from urllib import request"})
    assert "Import not allowed: urllib" in result


def test_execute_python_blocks_dynamic_import():
    execute_python = make_execute_python_tool()

    result = execute_python.invoke({"code": "__import__('os')"})
    assert "Import not allowed: os" in result


def test_execute_python_allows_safe_imports():
    execute_python = make_execute_python_tool()

    result = execute_python.invoke({"code": "import json; print(json.dumps({'a': 1}))"})
    assert '{"a": 1}' in result

    result = execute_python.invoke({"code": "import math; print(math.pi)"})
    assert "3.14" in result


def test_planner_uses_structured_output(temp_output_dir):
    class StructuredOnlyLLM:
        schema = None

        def with_structured_output(self, schema):
            self.schema = schema
            return self

        async def ainvoke(self, messages):
            return self.schema(
                goal="answer research query",
                steps=[{
                    "id": "s1",
                    "name": "search",
                    "worker_type": "research",
                    "description": "search papers",
                    "depends_on": [],
                }],
            )

    llm = StructuredOnlyLLM()
    state = {"messages": [HumanMessage(content="Find papers")], "output_dir": temp_output_dir}
    result = asyncio.run(planner.plan(
        state,
        llm,
        tools=[],
        worker_docs="- research: Search arxiv and cite papers",
        planner_consultations=False,
        worker_types=("research",),
    ))

    assert llm.schema is PlanOutput
    assert result["plan"]["steps"][0]["worker_type"] == "research"


def test_planner_rejects_invalid_plan_shape():
    bad_plan = {
        "goal": "test",
        "steps": [
            {"id": "s1", "name": "bad", "worker_type": "unknown", "description": "x", "depends_on": []}
        ],
    }

    with pytest.raises(ValueError, match="Unknown worker_type"):
        validate_plan_data(bad_plan, ("compute",))


def test_supervisor_routing():
    state = {"messages": [], "plan": None}
    result = supervise(state)
    assert result["next_action"] == "plan"
    assert route_action(result) == "plan"

    with pytest.raises(KeyError):
        route_action({})

    state = {"messages": [], "plan": None, "error": "planner failed"}
    result = supervise(state)
    assert result["next_action"] == "synthesize"

    state = {"plan": {"status": "active", "steps": [{"id": "s1", "status": "ready", "depends_on": []}]}}
    result = supervise(state)
    assert result["next_action"] == "execute"

    state = {"plan": {"status": "active", "steps": [{"id": "s1", "status": "completed", "depends_on": []}]}}
    result = supervise(state)
    assert result["next_action"] == "synthesize"


def test_router_picks_ready_step():
    plan = {
        "steps": [
            {"id": "s1", "status": "completed", "worker_type": "research", "depends_on": []},
            {"id": "s2", "status": "ready", "worker_type": "compute", "depends_on": ["s1"]},
            {"id": "s3", "status": "pending", "worker_type": "viz", "depends_on": ["s2"]},
        ]
    }
    state = {"plan": plan}
    result = route(state)
    assert result["current_step_id"] == "s2"
