from ..state import AgentState, get_ready_steps


def route(state: AgentState) -> dict:
    plan = state.get("plan")
    if not plan:
        return {"next_action": "plan"}

    ready = get_ready_steps(plan)
    if not ready:
        return {"next_action": "synthesize"}

    step = ready[0]
    new_steps = [{**s, "status": "running"} if s["id"] == step["id"] else s for s in plan["steps"]]
    return {"plan": {**plan, "steps": new_steps}, "current_step_id": step["id"]}


def route_to_worker(state: AgentState, workers: dict) -> str:
    plan = state.get("plan")
    step_id = state.get("current_step_id")
    if not plan or not step_id:
        return "supervisor"

    step = next((s for s in plan["steps"] if s["id"] == step_id), None)
    if not step or step["worker_type"] not in workers:
        return "supervisor"
    return step["worker_type"]
