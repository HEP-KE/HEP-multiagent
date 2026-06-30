from contextlib import nullcontext
from typing import Any, List, Callable

from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy

from .state import AgentState, get_dependency_context
from .config import WORKERS, get_worker_docs
from .nodes import planner, synthesis, supervisor, router, worker
from .features.lesson_memory import LessonMemory, recall, learn


LLM_RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, jitter=True)
MCP_RETRY = RetryPolicy(max_attempts=5, initial_interval=2.0, backoff_factor=2.0, max_interval=60.0, jitter=True)


def _log_lessons_recalled(logger, worker_type: str, lessons: str):
    if not lessons:
        logger.log("Memory", f"No past lessons for {worker_type} worker")
    else:
        count = lessons.count("\n- ")
        logger.log("Memory", f"Recalled {count} lesson(s) for {worker_type} worker\n{lessons}")


def _log_lesson_saved(logger, worker_type: str, task: str, error: str):
    logger.log("Memory", f"Saved lesson for {worker_type}: {task} → {error}")


def _format_plan_log(plan) -> str:
    lines = [f"Goal: {plan['goal']}\n"]
    for step in plan.get("steps", []):
        deps = f" (depends: {', '.join(step['depends_on'])})" if step.get("depends_on") else ""
        lines.append(f"- {step['id']} [{step['worker_type']}] {step['name']}{deps}")
        lines.append(f"  > {step['description']}")
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
    lesson_memory: LessonMemory = None,
    issue_tracking: bool = True,
    structured_worker_output: bool = False,
    run_local_tool_prototyping: bool = False,
    role_prompts: bool = True,
    diagnostics: Any = None,
):
    async def worker_node(s):
        plan = s.get("plan")
        step_id = s.get("current_step_id")
        step = next((st for st in plan["steps"] if st["id"] == step_id), None) if plan and step_id else None
        worker_type = step["worker_type"] if step else None
        agent_name = f"{worker_type}_worker" if worker_type else "worker"
        if diagnostics and step:
            diagnostics.validate_dependency_order(plan, step_id)
            diagnostics.event(agent_name, "started", f"Executing step {step_id}: {step['name']}")
        if logger and step:
            context, artifacts = get_dependency_context(plan, step_id)
            node_name = f"{step['worker_type'].title()} Worker: {step['name']}"
            inputs = [f"Task: {step['description']}"]
            if artifacts:
                inputs.append(f"Artifacts: {', '.join(artifacts)}")
            if context:
                inputs.append(f"Context from dependencies: {context}")
            logger.log(node_name, "\n".join(inputs))
        lessons = await recall(lesson_memory, worker_type)
        if logger and worker_type:
            _log_lessons_recalled(logger, worker_type, lessons)
        with diagnostics.agent_timer(agent_name) if diagnostics else nullcontext():
            result = await worker.execute(
                s,
                llm,
                tools,
                WORKERS,
                artifact_extensions,
                get_output_dir(),
                logger,
                notebook,
                lessons,
                issue_tracking=issue_tracking,
                structured_worker_output=structured_worker_output,
                run_local_tool_prototyping=run_local_tool_prototyping,
                role_prompts=role_prompts,
                diagnostics=diagnostics,
            )
        updated_step = next((st for st in result.get("plan", {}).get("steps", []) if st["id"] == step_id), {})
        task = step["description"] if step else ""
        status = updated_step.get("status")
        error = updated_step.get("error")
        if status == "failed" and error and logger:
            _log_lesson_saved(logger, worker_type, task, error)
        await learn(lesson_memory, worker_type, status, error, task, updated_step.get("output", ""))
        if logger and step:
            icon = "✓" if status == "completed" else "✗"
            outcome = f"Outcome: {icon} {status.upper()}"
            if error:
                outcome += f"\nError: {error}"
            if updated_step.get("artifacts"):
                outcome += f"\nFiles: {', '.join(updated_step['artifacts'])}"
            node_name = f"{step['worker_type'].title()} Worker: {step['name']}"
            logger.log(node_name, outcome)
        if diagnostics and step:
            diagnostics.finish_agent_step(agent_name, status or "failed", updated_step.get("artifacts", []), bool(updated_step.get("final_answer_produced")))
            diagnostics.event(agent_name, "completed" if status == "completed" else "failed", f"Step {step_id} ended with status {status}")
        return result

    async def planner_node(s):
        if diagnostics:
            diagnostics.event("planner", "started", "Creating execution plan")
        if logger:
            inputs = ["Creating execution plan"]
            query = ""
            for msg in s.get("messages", []):
                if hasattr(msg, "content"):
                    query = msg.content
                    break
            if query:
                inputs.append(f"Query: {query}")
            if s.get("planning_feedback"):
                inputs.append(f"Feedback: {s['planning_feedback']}")
            logger.log("Planner", "\n".join(inputs))
        with diagnostics.agent_timer("planner") if diagnostics else nullcontext():
            worker_docs = get_worker_docs() if role_prompts else ", ".join(WORKERS)
            result = await planner.plan(s, llm, tools, worker_docs, logger, diagnostics, role_prompts)
        if logger:
            plan = result.get("plan")
            if plan:
                logger.log("Planner", _format_plan_log(plan))
            elif result.get("error"):
                logger.log("Planner", f"Failed: {result['error']}")
        if diagnostics:
            if result.get("plan"):
                diagnostics.validate_plan(result["plan"], list(WORKERS))
                diagnostics.event("planner", "completed", f"Created {len(result['plan'].get('steps', []))}-step plan")
            else:
                diagnostics.event("planner", "failed", result.get("error", "Planner failed"))
        return result

    async def synthesis_node(s):
        if diagnostics:
            diagnostics.event("synthesis", "started", "Generating final report")
        if logger:
            plan = s.get("plan", {})
            steps = plan.get("steps", [])
            completed = [st["name"] for st in steps if st["status"] == "completed"]
            failed = [st["name"] for st in steps if st["status"] == "failed"]
            artifacts = []
            for st in steps:
                artifacts.extend(st.get("artifacts", []))
            inputs = ["Generating final report"]
            inputs.append(f"Completed steps: {', '.join(completed) if completed else 'none'}")
            if failed:
                inputs.append(f"Failed steps: {', '.join(failed)}")
            if artifacts:
                inputs.append(f"Artifacts: {', '.join(artifacts)}")
            logger.log("Synthesis", "\n".join(inputs))
        with diagnostics.agent_timer("synthesis") if diagnostics else nullcontext():
            result = await synthesis.synthesize(s, llm, report_writer, references, logger, diagnostics)
        if diagnostics:
            diagnostics.event("synthesis", "completed", "Final report generated")
        return result

    def supervisor_node(s):
        result = supervisor.supervise(s)
        if diagnostics:
            diagnostics.event("supervisor", "decision", result.get("next_action", "unknown"))
        if logger:
            action = result.get("next_action", "unknown")
            plan = s.get("plan")
            if plan:
                lines = [f"Decision: {action}"]
                for step in plan.get("steps", []):
                    status = step["status"]
                    if status == "completed":
                        mark = "[✓]"
                    elif status == "failed":
                        mark = "[✗]"
                    elif status == "skipped":
                        mark = "[-]"
                    elif status == "ready":
                        mark = "[>]"
                    else:
                        mark = "[ ]"
                    lines.append(f"  {mark} {step['name']}")
                logger.log("Supervisor", "\n".join(lines))
            else:
                logger.log("Supervisor", f"Decision: {action}")
        return result

    def router_node(s):
        result = router.route(s)
        if diagnostics:
            step_id = result.get("current_step_id")
            diagnostics.event("router", "routed", f"Current step: {step_id}" if step_id else "No runnable step")
        if logger:
            step_id = result.get("current_step_id")
            plan = result.get("plan") or s.get("plan")
            if step_id and plan:
                step = next((st for st in plan["steps"] if st["id"] == step_id), None)
                if step:
                    logger.log("Router", f"Routing {step['name']} → {step['worker_type'].title()} Worker")
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
