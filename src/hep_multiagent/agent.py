import os
import hashlib
import uuid
from typing import Any, Dict, List, Union

from langchain_core.messages import HumanMessage

from .config import (
    DEFAULT_EXTENSIONS, DEFAULT_OUTPUT_DIR,
    REPORTS, REFERENCES, SQLiteCheckpoint, APPROVAL, ExecutionNotebook,
)
from .workers.compute import set_code_approval, set_output_dir
from .features.config import AgentFeatures
from .features.diagnostics import RunDiagnostics
from .features.lesson_memory import LessonMemory
from .features.run_local_tools import set_run_local_tools_dir
from .graph import build_graph
from .features.agent_trace import MarkdownLogger
from .mcp import MCPManager


class Agent:
    def __init__(
        self,
        llm: Any,
        mcp_servers: Union[str, List[Dict[str, Any]]] = None,
        plan_approval: bool = False,
        lesson_memory: bool = True,
        features: Union[AgentFeatures, Dict[str, bool]] = None,
    ):
        self.llm = llm
        self.mcp_servers = mcp_servers
        self.artifact_extensions = DEFAULT_EXTENSIONS
        if isinstance(features, dict):
            features = AgentFeatures(**features)
        self.features = features or AgentFeatures(plan_approval=plan_approval, lesson_memory=lesson_memory)

        self.report = REPORTS["latex"]() if self.features.report else None
        self.references = REFERENCES["bibtex"]() if self.features.citations else None
        self.checkpoint = None
        self.approval = APPROVAL["interrupt"]() if self.features.plan_approval else APPROVAL["auto"]()
        set_code_approval(self.approval if self.features.python_execution_approval else None)

        self.output_dir = None
        self.logger = MarkdownLogger() if self.features.execution_log else None
        self.notebook = ExecutionNotebook() if self.features.replay_notebook else None
        self.diagnostics = None
        self.lesson_memory = None
        self._mcp = MCPManager()
        self._graph = None

    def __await__(self):
        return self._init().__await__()

    async def _init(self):
        if self.mcp_servers:
            await self._mcp.load(self.mcp_servers)
        return self

    @property
    def tools(self) -> List:
        if not self._mcp.tools:
            raise RuntimeError("No tools loaded. Ensure 'await Agent(...)' was used and mcp_servers is set.")
        return self._mcp.tools

    def print_tools(self):
        for t in self.tools:
            print(f"- {t.name}")

    def _get_thread_id(self, query: str, resume: bool) -> str:
        if resume:
            return hashlib.sha256(query.encode()).hexdigest()[:16]
        return f"run-{uuid.uuid4().hex[:12]}"

    async def run(self, query: str, output_dir: str = None, resume: bool = False) -> dict:
        self.output_dir = os.path.abspath(output_dir or DEFAULT_OUTPUT_DIR)
        os.makedirs(self.output_dir, exist_ok=True)
        set_output_dir(self.output_dir)
        set_run_local_tools_dir(self.output_dir)

        if self.logger:
            self.logger.init(self.output_dir)
            self.logger.log("Start", f"Query: {query[:100]}...")
        self.diagnostics = RunDiagnostics(query, self.output_dir, self.llm, self.features, self.mcp_servers) if self.features.run_diagnostics else None
        if self.diagnostics:
            self.diagnostics.event("run", "started", "Run started")

        if self.checkpoint is None:
            db_path = os.path.join(os.getcwd(), "checkpoint.db")
            self.checkpoint = SQLiteCheckpoint(db_path)
            if self.features.lesson_memory:
                self.lesson_memory = LessonMemory(db_path)
                await self.lesson_memory.init()

        if self.mcp_servers:
            if self.logger:
                self.logger.log("MCP", "Loading MCP servers...")
            if self.diagnostics:
                self.diagnostics.event("mcp", "started", "Loading MCP servers")
            try:
                await self._mcp.load(self.mcp_servers)
            except Exception as e:
                if self.diagnostics:
                    self.diagnostics.failure("mcp_server_failure", "mcp", None, str(e), False, "mcp_load_failed")
                raise
            if self.logger:
                self.logger.log("MCP", f"Loaded {len(self._mcp.tools)} tools")
            if self.diagnostics:
                self.diagnostics.event("mcp", "completed", f"Loaded {len(self._mcp.tools)} tools")
        if self.notebook:
            self.notebook.init(self.output_dir, self._mcp.tool_sources, self.logger)
        thread_id = self._get_thread_id(query, resume)
        config = {"configurable": {"thread_id": thread_id}}

        try:
            async with self.checkpoint.checkpointer() as checkpointer:
                existing_state = None
                if resume:
                    existing_state = await self.checkpoint.get_state(checkpointer, thread_id)

                if existing_state and resume:
                    plan = existing_state.get("plan")
                    if plan:
                        completed = sum(1 for s in plan["steps"] if s["status"] == "completed")
                        total = len(plan["steps"])
                        print(f"Resuming run: {completed}/{total} steps completed")
                        if self.logger:
                            self.logger.log("Resume", f"{completed}/{total} steps completed")
                    initial = None
                else:
                    if resume:
                        print("No matching prior run found, starting fresh")
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
                    get_output_dir=lambda: self.output_dir,
                    logger=self.logger,
                    notebook=self.notebook,
                    lesson_memory=self.lesson_memory,
                    issue_tracking=self.features.issue_tracking,
                    structured_worker_output=self.features.structured_worker_output,
                    run_local_tool_prototyping=self.features.run_local_tool_prototyping,
                    role_prompts=self.features.role_prompts,
                    planner_consultations=self.features.planner_consultations,
                    enabled_worker_types=self.features.enabled_workers,
                    diagnostics=self.diagnostics,
                )
                if self.diagnostics:
                    self.diagnostics.configure_tools(self._mcp.tools, self._mcp.tool_sources, list(self.features.enabled_workers))

                if initial:
                    result = await self._graph.ainvoke(initial, config)
                else:
                    result = await self._graph.ainvoke(None, config)

                while result.get("next_action") == "await_approval":
                    plan = result.get("plan")
                    if not plan:
                        break

                    approval_response = self.approval.request_approval(plan)
                    update = {
                        "user_approved": approval_response.approved,
                        "planning_feedback": approval_response.feedback,
                    }
                    if approval_response.approved:
                        update["plan"] = {**plan, "status": "active"}

                    result = await self._graph.ainvoke(update, config)

        except Exception as e:
            if self.logger:
                self.logger.error(e)
            if self.diagnostics:
                self.diagnostics.event("run", "failed", str(e))
                self.diagnostics.finalize("failed")
            if "Connection" in type(e).__name__:
                raise RuntimeError(f"LLM connection failed: {e}") from None
            raise
        finally:
            if self.logger:
                self.logger.close()
            if self.notebook:
                self.notebook.close()
            await self._mcp.close()

        if self.diagnostics:
            self.diagnostics.finalize("completed", result)

        return result
