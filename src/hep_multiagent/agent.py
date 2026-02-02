import os
import hashlib
import uuid
from typing import Any, List, Union

from langchain_core.messages import HumanMessage

from .config import (
    ACADEMIC_REPORT, DEFAULT_EXTENSIONS, DEFAULT_OUTPUT_DIR,
    REPORTS, REFERENCES, SQLiteCheckpoint, APPROVAL, ExecutionNotebook,
)
from .graph import build_graph
from .features.agent_trace import MarkdownLogger
from .mcp import MCPManager


class Agent:
    def __init__(
        self,
        llm: Any,
        mcp_servers: Union[str, List[str]] = None,
        approval: bool = False,
    ):
        self.llm = llm
        self.mcp_servers = mcp_servers
        self.artifact_extensions = DEFAULT_EXTENSIONS

        self.report = REPORTS["latex"]() if ACADEMIC_REPORT else None
        self.references = REFERENCES["bibtex"]() if ACADEMIC_REPORT else None
        self.checkpoint = None  # initialized in run() with cwd path
        self.approval = APPROVAL["interrupt"]() if approval else APPROVAL["auto"]()

        self.output_dir = None
        self.logger = MarkdownLogger()
        self.notebook = ExecutionNotebook()
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

        self.logger.init(self.output_dir)
        self.logger.log("Start", f"Query: {query[:100]}...")

        if self.checkpoint is None:
            db_path = os.path.join(os.getcwd(), "checkpoint.db")
            self.checkpoint = SQLiteCheckpoint(db_path)

        if self.mcp_servers:
            self.logger.log("MCP", "Loading MCP servers...")
            await self._mcp.load(self.mcp_servers, output_dir=self.output_dir)
            self.logger.log("MCP", f"Loaded {len(self._mcp.tools)} tools")
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
                )

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
            self.logger.error(e)
            if "Connection" in type(e).__name__:
                raise RuntimeError(f"LLM connection failed: {e}") from None
            raise
        finally:
            self.logger.close()
            self.notebook.close()
            self._mcp.uninstall()

        return result
