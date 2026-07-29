from ..state import AgentState, get_ready_steps, is_plan_complete, has_plan_failed, has_stuck_steps


def supervise(state: AgentState) -> dict:
    plan = state.get("plan")

    if state.get("error"):
        return {"next_action": "synthesize"}
    if plan is None:
        return {"next_action": "plan"}
    if is_plan_complete(plan):
        return {"next_action": "synthesize"}
    if has_plan_failed(plan):
        return {"next_action": "synthesize"}
    if get_ready_steps(plan):
        return {"next_action": "execute"}
    if has_stuck_steps(plan):
        return {"next_action": "synthesize"}
    raise RuntimeError("Plan has no ready, running, completed, or failed steps.")


def route_action(state: AgentState) -> str:
    return state["next_action"]
