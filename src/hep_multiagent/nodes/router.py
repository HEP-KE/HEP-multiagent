from ..state import AgentState, get_ready_steps


def route(state: AgentState) -> dict:
    plan = state["plan"]
    ready = get_ready_steps(plan)
    if not ready:
        return {"next_action": "synthesize"}

    step = ready[0]
    new_steps = [{**s, "status": "running"} if s["id"] == step["id"] else s for s in plan["steps"]]
    return {"plan": {**plan, "steps": new_steps}, "current_step_id": step["id"]}


def route_to_worker(state: AgentState) -> str:
    step_id = state["current_step_id"]
    step = next(s for s in state["plan"]["steps"] if s["id"] == step_id)
    return step["worker_type"]
