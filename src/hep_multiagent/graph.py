from typing import Any, List, Callable

from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy

from .state import AgentState
from .config import WORKERS, get_worker_docs
from .nodes import planner, synthesis, supervisor, router, worker


LLM_RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, jitter=True)
MCP_RETRY = RetryPolicy(max_attempts=5, initial_interval=2.0, backoff_factor=2.0, max_interval=60.0, jitter=True)


def _supervisor_reason(state, plan, action):
    if action == "plan":
        if state.get("user_approved") is False:
            return f"User rejected plan. Feedback: {state.get('planning_feedback', 'none')}"
        return "No plan exists yet"
    if action == "await_approval":
        return "Plan is draft, awaiting user approval"
    if action == "synthesize":
        if not plan:
            return "No plan to execute"
        completed = sum(1 for s in plan.get("steps", []) if s["status"] == "completed")
        failed = sum(1 for s in plan.get("steps", []) if s["status"] == "failed")
        return f"Plan finished: {completed} completed, {failed} failed"
    if action == "execute":
        ready = [s["name"] for s in plan.get("steps", []) if s["status"] == "ready"]
        return f"Ready steps: {', '.join(ready)}"
    return ""


def _log_worker_result(logger, step, updated_step):
    status = updated_step.get("status", "unknown")
    artifacts = updated_step.get("artifacts", [])
    solution = (updated_step.get("solution") or "")[:300]
    error = updated_step.get("error")
    lines = [f"Finished: **{step['name']}** ({status})"]
    if artifacts:
        lines.append(f"\nArtifacts: {', '.join(artifacts)}")
    if solution:
        lines.append(f"\nSolution: {solution}")
    if error:
        lines.append(f"\nError: {error}")
    logger.log("Worker", "\n".join(lines))


def _format_plan_log(plan) -> str:
    lines = [f"**Goal**: {plan['goal']}\n"]
    for step in plan.get("steps", []):
        deps = f" (depends: {', '.join(step['depends_on'])})" if step.get("depends_on") else ""
        lines.append(f"- `{step['id']}` [{step['worker_type']}] {step['name']}{deps}")
        lines.append(f"  > {step['description'][:200]}")
    return "\n".join(lines)


def build_graph(
    llm: Any,
    tools: List,
    report_writer: Any,
    references: Any,
    artifact_extensions: List[str],
    checkpointer: Any,
    get_output_dir: Callable[[], str],
    logger: Any = None,
    notebook: Any = None,
):
    async def worker_node(s):
        plan = s.get("plan")
        step_id = s.get("current_step_id")
        step = next((st for st in plan["steps"] if st["id"] == step_id), None) if plan and step_id else None
        if logger and step:
            logger.log("Worker", f"Executing: **{step['name']}**\n\n> {step['description'][:300]}")
        result = await worker.execute(s, llm, tools, WORKERS, artifact_extensions, get_output_dir(), logger, notebook)
        if logger and step:
            updated_step = next((st for st in result.get("plan", {}).get("steps", []) if st["id"] == step_id), {})
            _log_worker_result(logger, step, updated_step)
        return result

    async def planner_node(s):
        if logger:
            logger.log("Planner", "Creating execution plan...")
        result = await planner.plan(s, llm, tools, get_worker_docs(), logger)
        if logger:
            plan = result.get("plan")
            if plan:
                logger.log("Planner", _format_plan_log(plan))
            elif result.get("error"):
                logger.log("Planner", f"Failed: {result['error']}")
        return result

    async def synthesis_node(s):
        if logger:
            logger.log("Synthesis", "Generating final report...")
        return await synthesis.synthesize(s, llm, report_writer, references, logger)

    def supervisor_node(s):
        if logger and not s.get("plan"):
            logger.log("Supervisor", "Analyzing query...")
        result = supervisor.supervise(s)
        if logger:
            action = result.get("next_action", "unknown")
            plan = s.get("plan")
            reason = _supervisor_reason(s, plan, action)
            logger.log("Supervisor", f"Decision: **{action}**\n\n{reason}")
        return result

    def router_node(s):
        result = router.route(s)
        if logger:
            step_id = result.get("current_step_id")
            plan = result.get("plan") or s.get("plan")
            if step_id and plan:
                step = next((st for st in plan["steps"] if st["id"] == step_id), None)
                if step:
                    logger.log("Router", f"Routing `{step['name']}` → **{step['worker_type']}** worker")
        return result

    graph = StateGraph(AgentState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node, retry=LLM_RETRY)
    graph.add_node("router", router_node)
    graph.add_node("worker", worker_node, retry=MCP_RETRY)
    graph.add_node("synthesis", synthesis_node, retry=LLM_RETRY)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", supervisor.route_action, {
        "plan": "planner",
        "execute": "router",
        "synthesize": "synthesis",
        "await_approval": END,
        "end": END,
    })
    graph.add_edge("planner", "supervisor")

    worker_routes = {name: "worker" for name in WORKERS}
    worker_routes["supervisor"] = "supervisor"
    graph.add_conditional_edges("router", lambda s: router.route_to_worker(s, WORKERS), worker_routes)

    graph.add_edge("worker", "supervisor")
    graph.add_edge("synthesis", END)

    return graph.compile(checkpointer=checkpointer)
