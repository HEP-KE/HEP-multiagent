from ..state import AgentState, get_ready_steps, is_plan_complete, has_plan_failed, has_stuck_steps


def supervise(state: AgentState) -> dict:
    plan = state.get("plan")

    if plan is None:
        return {"next_action": "plan"}
    if state.get("user_approved") is None and plan["status"] == "draft":
        return {"next_action": "await_approval"}
    if state.get("user_approved") is False:
        return {"next_action": "plan"}
    if is_plan_complete(plan):
        return {"next_action": "synthesize"}
    if has_plan_failed(plan):
        return {"next_action": "synthesize"}
    if get_ready_steps(plan):
        return {"next_action": "execute"}
    if has_stuck_steps(plan):
        return {"next_action": "synthesize"}
    return {"next_action": "synthesize"}


def route_action(state: AgentState) -> str:
    return state.get("next_action", "end")
