from typing import Any, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..config import WORKER_TOOLS
from ..state import AgentState, get_dependency_context
from ..worker import build_worker_prompt
from .. import worker_graph

MAX_RETRIES = 2


async def execute(
    state: AgentState,
    llm: Any,
    tools: List,
    workers: dict,
    artifact_extensions: List[str],
    default_output_dir: str,
    logger: Any = None,
    notebook: Any = None,
) -> dict:
    plan = state.get("plan")
    step_id = state.get("current_step_id")
    step = next((s for s in plan["steps"] if s["id"] == step_id), None)
    if not step:
        return {}

    context, artifacts = get_dependency_context(plan, step_id)
    output_dir = state.get("output_dir", default_output_dir)
    previous_attempts = step.get("attempts", [])
    research_context = plan.get("research_context")

    worker_tools = list(tools)
    if step["worker_type"] in WORKER_TOOLS:
        worker_tools.extend(WORKER_TOOLS[step["worker_type"]]())

    prompt = workers.get(step["worker_type"], workers["data"])
    task = build_worker_prompt(step["description"], output_dir, artifacts, context, previous_attempts, research_context)

    graph = worker_graph.build(llm, worker_tools, artifact_extensions, logger, notebook, step["worker_type"])

    result = await graph.ainvoke({
        "messages": [SystemMessage(content=prompt), HumanMessage(content=task)],
        "iteration": 0,
        "max_iterations": 25,
        "artifacts": list(artifacts),
    })

    solution = result.get("solution", "")
    error = result.get("error")
    output = "\n\n".join(result.get("outputs", []))
    if solution:
        output += f"\n\n## Answer\n{solution}"

    # Detect if worker explicitly failed (data unavailable, etc.)
    is_explicit_failure = solution and solution.strip().upper().startswith("FAILED:")
    if is_explicit_failure:
        error = solution.strip()
        solution = ""

    attempt = {"output": output[:1000], "error": error, "tool_calls": result.get("tool_calls", [])}
    attempts = previous_attempts + [attempt]

    if solution and not is_explicit_failure:
        status = "completed"
        error = None
    elif error:
        status = "ready" if len(attempts) < MAX_RETRIES else "failed"
        if logger and status == "ready":
            logger.log("Worker", f"Retrying (attempt {len(attempts)}/{MAX_RETRIES}): {error}")
    else:
        status = "failed"
        error = "Worker did not produce a solution"

    new_steps = _update_steps(plan, step_id, status, output, solution, result.get("artifacts", []), error, attempts)

    status_msg = "Completed" if status == "completed" else "Failed" if status == "failed" else "Retrying"
    return {
        "plan": {**plan, "steps": new_steps},
        "current_step_id": None,
        "messages": [AIMessage(content=f"{status_msg}: {step['name']}")],
    }


def _update_steps(plan, step_id, status, output, solution, artifacts, error, attempts):
    new_steps = []
    for s in plan["steps"]:
        if s["id"] == step_id:
            new_steps.append({
                **s,
                "status": status,
                "output": output,
                "solution": solution,
                "artifacts": artifacts,
                "error": error if status == "failed" else None,
                "attempts": attempts,
            })
        else:
            new_steps.append(s.copy())

    if status == "completed":
        completed = {s["id"] for s in new_steps if s["status"] == "completed"}
        for i, s in enumerate(new_steps):
            if s["status"] == "pending" and all(dep in completed for dep in s["depends_on"]):
                new_steps[i] = {**s, "status": "ready"}

    return new_steps
