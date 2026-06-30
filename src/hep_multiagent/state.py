from typing import TypedDict, Optional, List, Annotated, Literal
from operator import add


StepStatus = Literal["pending", "ready", "running", "completed", "failed", "blocked"]
NextAction = Literal["plan", "execute", "synthesize", "await_approval", "end"]


class StepAttempt(TypedDict):
    output: Optional[str]
    error: Optional[str]
    tool_calls: List[str]


class PlanStep(TypedDict):
    id: str
    name: str
    worker_type: str
    description: str
    depends_on: List[str]
    status: StepStatus
    output: Optional[str]
    solution: Optional[str]
    artifacts: List[str]
    error: Optional[str]
    attempts: List[StepAttempt]
    final_answer_produced: bool
    structured_output: Optional[dict]


class Plan(TypedDict, total=False):
    id: str
    goal: str
    status: Literal["draft", "active", "completed", "failed"]
    steps: List[PlanStep]
    research_context: Optional[str]


class AgentState(TypedDict, total=False):
    messages: Annotated[List, add]
    plan: Optional[Plan]
    current_step_id: Optional[str]
    next_action: NextAction
    final_report: Optional[str]
    user_approved: Optional[bool]
    planning_feedback: Optional[str]
    output_dir: str
    tool_issues: Annotated[List[str], add]


def get_dependency_context(plan: Plan, step_id: str) -> tuple:
    if not plan or not plan.get("steps"):
        return "", []

    current = next((s for s in plan["steps"] if s["id"] == step_id), None)
    if not current:
        return "", []

    depends_on = set(current.get("depends_on", []))
    if not depends_on:
        return "", []

    parts = []
    artifacts = []

    for step in plan["steps"]:
        if step["id"] in depends_on and step["status"] == "completed":
            parts.append(f"## From: {step['name']}")
            if step.get("solution"):
                parts.append(step["solution"])
            if step.get("artifacts"):
                artifacts.extend(step["artifacts"])
            parts.append("")

    return "\n".join(parts).strip(), artifacts


def get_ready_steps(plan: Plan) -> List[PlanStep]:
    if not plan or not plan.get("steps"):
        return []

    completed = {s["id"] for s in plan["steps"] if s["status"] == "completed"}
    ready = []

    for step in plan["steps"]:
        if step["status"] == "ready":
            if all(dep in completed for dep in step["depends_on"]):
                ready.append(step)

    return ready


def has_stuck_steps(plan: Plan) -> bool:
    if not plan or not plan.get("steps"):
        return False
    return any(s["status"] == "running" for s in plan["steps"])


def is_plan_complete(plan: Plan) -> bool:
    if not plan or not plan.get("steps"):
        return False
    return all(s["status"] == "completed" for s in plan["steps"])


def has_plan_failed(plan: Plan) -> bool:
    if not plan or not plan.get("steps"):
        return False
    return any(s["status"] == "failed" for s in plan["steps"])
