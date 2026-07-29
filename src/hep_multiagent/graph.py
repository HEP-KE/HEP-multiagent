from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from .config import WORKERS, get_worker_docs
from .nodes import planner, router, supervisor, synthesis, worker
from .state import AgentState, get_dependency_context


LLM_RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, jitter=True)
MCP_RETRY = RetryPolicy(max_attempts=5, initial_interval=2.0, backoff_factor=2.0, max_interval=60.0, jitter=True)


def _find_step(plan: dict, step_id: str) -> dict:
    for step in plan["steps"]:
        if step["id"] == step_id:
            return step
    raise RuntimeError(f"Current step not found: {step_id}")


def _format_plan_log(plan: dict) -> str:
    lines = [f"Goal: {plan['goal']}"]
    for step in plan.get("steps", []):
        deps = f" (depends: {', '.join(step['depends_on'])})" if step.get("depends_on") else ""
        lines.append(f"- {step['id']} [{step['worker_type']}] {step['name']}{deps}")
        lines.append(f"  > {step['description']}")
    return "\n".join(lines)


def _log_worker_start(logger, plan: dict, step: dict) -> None:
    context, artifacts = get_dependency_context(plan, step["id"])
    lines = [f"Task: {step['description']}"]
    if artifacts:
        lines.append(f"Artifacts: {', '.join(artifacts)}")
    if context:
        lines.append(f"Context from dependencies: {context}")
    logger.log(f"{step['worker_type'].title()} Worker: {step['name']}", "\n".join(lines))


def _log_worker_result(logger, step: dict, updated_step: dict) -> None:
    status = updated_step.get("status", "unknown")
    lines = [f"Outcome: {status.upper()}"]
    if updated_step.get("error"):
        lines.append(f"Error: {updated_step['error']}")
    if updated_step.get("artifacts"):
        lines.append(f"Files: {', '.join(updated_step['artifacts'])}")
    logger.log(f"{step['worker_type'].title()} Worker: {step['name']}", "\n".join(lines))


def build_graph(
    llm: Any,
    tools: list,
    report_writer: Any,
    references: Any,
    artifact_extensions: list[str],
    checkpointer: Any,
    logger: Any = None,
    notebook: Any = None,
    issue_tracking: bool = True,
    structured_worker_output: bool = True,
    planner_consultations: bool = True,
    recorder: Any = None,
    tool_sources: dict | None = None,
):
    active_workers = WORKERS

    async def planner_node(state: AgentState):
        if logger:
            lines = ["Creating execution plan"]
            query = next((msg.content for msg in state.get("messages", []) if hasattr(msg, "content")), "")
            if query:
                lines.append(f"Query: {query}")
            logger.log("Planner", "\n".join(lines))

        worker_types = tuple(WORKERS)
        worker_docs = get_worker_docs(worker_types)
        result = await planner.plan(
            state,
            llm,
            tools,
            worker_docs,
            logger,
            planner_consultations,
            worker_types,
        )

        if logger:
            if result.get("plan"):
                logger.log("Planner", _format_plan_log(result["plan"]))
            elif result.get("error"):
                logger.log("Planner", f"Failed: {result['error']}")
        return result

    async def worker_node(state: AgentState):
        plan = state["plan"]
        step_id = state["current_step_id"]
        step = _find_step(plan, step_id)

        if logger:
            _log_worker_start(logger, plan, step)

        result = await worker.execute(
            state,
            llm,
            tools,
            active_workers,
            artifact_extensions,
            logger,
            notebook,
            issue_tracking=issue_tracking,
            structured_worker_output=structured_worker_output,
            recorder=recorder,
            tool_sources=tool_sources,
        )

        if logger:
            updated_step = _find_step(result["plan"], step_id)
            _log_worker_result(logger, step, updated_step)
        return result

    async def synthesis_node(state: AgentState):
        if logger:
            plan = state.get("plan", {})
            steps = plan.get("steps", [])
            completed = [step["name"] for step in steps if step["status"] == "completed"]
            failed = [step["name"] for step in steps if step["status"] == "failed"]
            artifacts = [artifact for step in steps for artifact in step.get("artifacts", [])]
            lines = ["Generating final report"]
            lines.append(f"Completed steps: {', '.join(completed) if completed else 'none'}")
            if failed:
                lines.append(f"Failed steps: {', '.join(failed)}")
            if artifacts:
                lines.append(f"Artifacts: {', '.join(artifacts)}")
            logger.log("Synthesis", "\n".join(lines))
        return await synthesis.synthesize(state, llm, report_writer, references, logger)

    def supervisor_node(state: AgentState):
        result = supervisor.supervise(state)
        if logger:
            action = result.get("next_action", "unknown")
            plan = state.get("plan")
            if not plan:
                logger.log("Supervisor", f"Decision: {action}")
                return result

            lines = [f"Decision: {action}"]
            marks = {
                "completed": "[done]",
                "failed": "[failed]",
                "skipped": "[skipped]",
                "ready": "[ready]",
                "running": "[running]",
            }
            for step in plan.get("steps", []):
                lines.append(f"  {marks.get(step['status'], '[pending]')} {step['name']}")
            logger.log("Supervisor", "\n".join(lines))
        return result

    def router_node(state: AgentState):
        result = router.route(state)
        if logger:
            step = _find_step(result["plan"], result["current_step_id"])
            logger.log("Router", f"Routing {step['name']} -> {step['worker_type'].title()} Worker")
        return result

    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node, retry_policy=LLM_RETRY)
    graph.add_node("router", router_node)
    graph.add_node("worker", worker_node, retry_policy=MCP_RETRY)
    graph.add_node("synthesis", synthesis_node, retry_policy=LLM_RETRY)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", supervisor.route_action, {
        "plan": "planner",
        "execute": "router",
        "synthesize": "synthesis",
        "end": END,
    })
    graph.add_edge("planner", "supervisor")
    graph.add_conditional_edges(
        "router",
        router.route_to_worker,
        {name: "worker" for name in active_workers},
    )
    graph.add_edge("worker", "supervisor")
    graph.add_edge("synthesis", END)

    return graph.compile(checkpointer=checkpointer)
