import hashlib
import os
import uuid
from typing import Any

from langchain_core.messages import HumanMessage

from .config import (
    DEFAULT_EXTENSIONS, DEFAULT_OUTPUT_DIR,
    REPORTS, REFERENCES, SQLiteCheckpoint, ExecutionNotebook,
)
from .features.config import AgentFeatures
from .graph import build_graph
from .features.agent_trace import MarkdownLogger
from .features.run_record import RunRecorder
from .mcp import MCPManager


class Agent:
    def __init__(
        self,
        llm: Any,
        mcp_servers: list[dict[str, Any]] | None = None,
        features: AgentFeatures | dict[str, bool] | None = None,
    ):
        self.llm = llm
        self.mcp_servers = mcp_servers
        self.artifact_extensions = DEFAULT_EXTENSIONS
        if isinstance(features, dict):
            features = AgentFeatures(**features)
        self.features = features if features is not None else AgentFeatures()

        self.report = REPORTS["latex"]() if self.features.report else None
        self.references = REFERENCES["bibtex"]() if self.features.citations else None
        self.checkpoint = None

        self.output_dir = None
        self.logger = MarkdownLogger() if self.features.execution_log else None
        self.notebook = ExecutionNotebook() if self.features.replay_notebook else None
        self._mcp = MCPManager()
        self._graph = None

    def _get_thread_id(self, query: str, resume: bool) -> str:
        if resume:
            return hashlib.sha256(query.encode()).hexdigest()[:16]
        return f"run-{uuid.uuid4().hex[:12]}"

    async def run(self, query: str, output_dir: str = None, resume: bool = False) -> dict:
        self.output_dir = os.path.abspath(output_dir or DEFAULT_OUTPUT_DIR)
        os.makedirs(self.output_dir, exist_ok=True)
        recorder = RunRecorder()
        recorder.start(query, self.output_dir, self.mcp_servers)
        result = None
        run_error = None

        if self.logger:
            self.logger.init(self.output_dir)
            self.logger.log("Start", f"Query: {query[:100]}...")

        if self.checkpoint is None:
            db_path = os.path.join(self.output_dir, "checkpoint.db")
            self.checkpoint = SQLiteCheckpoint(db_path)

        if self.mcp_servers:
            if self.logger:
                self.logger.log("MCP", "Loading MCP servers...")
            await self._mcp.load(self.mcp_servers)
            recorder.set_tools(self._mcp.tools)
            if self.logger:
                self.logger.log("MCP", f"Loaded {len(self._mcp.tools)} tools")
        if self.notebook:
            self.notebook.init(self.output_dir, self._mcp.tool_sources, self.logger)
        thread_id = self._get_thread_id(query, resume)
        config = {"configurable": {"thread_id": thread_id}}

        try:
            async with self.checkpoint.checkpointer() as checkpointer:
                existing_state = None
                if resume:
                    existing_state = await self.checkpoint.get_state(checkpointer, thread_id)

                if resume and not existing_state:
                    raise RuntimeError("No checkpoint found for this query.")

                if existing_state:
                    plan = existing_state.get("plan")
                    if plan:
                        completed = sum(1 for s in plan["steps"] if s["status"] == "completed")
                        total = len(plan["steps"])
                        print(f"Resuming run: {completed}/{total} steps completed")
                        if self.logger:
                            self.logger.log("Resume", f"{completed}/{total} steps completed")
                    initial = None
                else:
                    initial = {
                        "messages": [HumanMessage(content=query)],
                        "next_action": "plan",
                        "output_dir": self.output_dir,
                    }

                self._graph = build_graph(
                    llm=self.llm,
                    tools=self._mcp.tools,
                    report_writer=self.report,
                    references=self.references,
                    artifact_extensions=self.artifact_extensions,
                    checkpointer=checkpointer,
                    logger=self.logger,
                    notebook=self.notebook,
                    issue_tracking=self.features.issue_tracking,
                    structured_worker_output=self.features.structured_worker_output,
                    planner_consultations=self.features.planner_consultations,
                    recorder=recorder,
                    tool_sources=self._mcp.tool_sources,
                )

                if initial:
                    result = await self._graph.ainvoke(initial, config)
                else:
                    result = await self._graph.ainvoke(None, config)

        except Exception as e:
            run_error = f"{type(e).__name__}: {e}"
            if self.logger:
                self.logger.error(e)
            raise
        finally:
            recorder.finish(result, run_error)
            if self.logger:
                self.logger.close()
            await self._mcp.close()

        return result
