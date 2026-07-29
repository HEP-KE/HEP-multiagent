from langchain_core.tools import tool
from . import validators as validate


@tool
def log_issue(component: str, problem: str, suggestion: str) -> str:
    """Log an issue or tool recommendation for developer review. Call when you:
    - Encounter a tool failure or unexpected result
    - Write code because no tool exists
    - Notice an opportunity for a new tool

    Args:
        component: Worker or tool name (e.g., "compute", "create_bar_chart")
        problem: What went wrong or what's missing
        suggestion: Recommended fix or new tool

    Returns:
        Confirmation for developer review.
    """
    try:
        validate.non_empty(component, "component")
        validate.non_empty(problem, "problem")
        validate.non_empty(suggestion, "suggestion")
    except ValueError as e:
        return f"Error: {e}"

    return f"ISSUE_LOGGED: [{component}] {problem} -> {suggestion}"


def parse_issue(result: str) -> dict | None:
    if not result.startswith("ISSUE_LOGGED:"):
        return None
    content = result[len("ISSUE_LOGGED:"):].strip()
    if not content.startswith("[") or "]" not in content or " -> " not in content:
        return None
    component = content[1:content.find("]")]
    rest = content[content.find("]") + 1:].strip()
    problem, suggestion = rest.split(" -> ", 1)
    return {"component": component, "problem": problem.strip(), "suggestion": suggestion.strip()}


def format_issues_for_report(issues: list[str]) -> str:
    if not issues:
        return ""
    parsed = [p for p in (parse_issue(i) for i in issues) if p]
    if not parsed:
        return ""
    lines = []
    for issue in parsed:
        lines.append(f"- {issue['component']}: {issue['problem']} -> {issue['suggestion']}")
    return "\n".join(lines)
