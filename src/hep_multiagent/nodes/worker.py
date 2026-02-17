from typing import Any, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..config import WORKER_TOOLS
from ..state import AgentState, get_dependency_context
from ..worker import build_worker_prompt, extract_artifacts, normalize_tool_result
from ..features.agent_tools import final_answer
from ..features.issue_tracker import log_issue

MAX_RETRIES = 2
MAX_ITERATIONS = 15


async def execute(
    state: AgentState,
    llm: Any,
    tools: List,
    workers: dict,
    artifact_extensions: List[str],
    default_output_dir: str,
    logger: Any = None,
    notebook: Any = None,
    lessons: str = "",
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

    worker_tools = list(tools) + [final_answer, log_issue]
    if step["worker_type"] in WORKER_TOOLS:
        worker_tools.extend(WORKER_TOOLS[step["worker_type"]]())

    prompt = workers.get(step["worker_type"], workers["data"])
    task = build_worker_prompt(step["description"], output_dir, artifacts, context, previous_attempts, research_context, lessons)

    model = llm.bind_tools(worker_tools)
    messages = [SystemMessage(content=prompt), HumanMessage(content=task)]
    output_parts, tool_calls_made, new_artifacts = [], [], list(artifacts)
    solution, error = "", None

    for iteration in range(MAX_ITERATIONS):
        try:
            response = await model.ainvoke(messages)
        except Exception as e:
            error = f"Model error: {e}"
            break

        messages.append(response)
        if logger and response.content:
            logger.thought(response.content)

        if not response.tool_calls:
            solution = response.content or ""
            break

        for tc in response.tool_calls:
            name, args, tc_id = tc["name"], tc["args"], tc["id"]

            if name == "final_answer":
                solution = f"{args.get('outcome', 'success')}: {args.get('message', '')}"
                messages.append(ToolMessage(content=solution, tool_call_id=tc_id))
                break

            tool_fn = next((t for t in worker_tools if t.name == name), None)
            if not tool_fn:
                result_str = f"Tool '{name}' not found"
            else:
                try:
                    result = await tool_fn.ainvoke(args)
                except NotImplementedError:
                    result = tool_fn.invoke(args)
                except Exception as e:
                    result = f"ERROR: {e}\n\nAnalyze this error and retry with corrected parameters."
                result_str = normalize_tool_result(result)

            tool_calls_made.append(name)
            output_parts.append(f"[{name}]: {result_str[:500]}")
            new_artifacts.extend(extract_artifacts(result_str, artifact_extensions))
            messages.append(ToolMessage(content=result_str, tool_call_id=tc_id))

            if logger:
                logger.tool_call(name, args, result_str)
            if notebook and name not in ("final_answer", "log_issue"):
                notebook.tool_call(name, args, result_str, step["worker_type"])

        if solution:
            break

    output = "\n\n".join(output_parts)
    if solution:
        output += f"\n\n## Answer\n{solution}"

    has_success = solution.startswith("success:")
    has_failure = solution.startswith("failed:")
    attempt = {"output": output, "error": error, "tool_calls": tool_calls_made}
    attempts = previous_attempts + [attempt]

    if has_failure:
        status, error, solution = "failed", solution.strip(), ""
    elif has_success:
        status, error = "completed", None
    elif solution:
        error = "Call final_answer('success', summary) or final_answer('failed', reason) to complete."
        status = "ready" if len(attempts) < MAX_RETRIES else "failed"
    else:
        status, error = "failed", error or "No solution produced"

    new_steps = _update_steps(plan, step_id, status, output, solution, new_artifacts, error, attempts)
    return {
        "plan": {**plan, "steps": new_steps},
        "current_step_id": None,
        "messages": [AIMessage(content=f"{'Completed' if status == 'completed' else 'Failed' if status == 'failed' else 'Retrying'}: {step['name']}")],
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
