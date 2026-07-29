import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..config import get_worker_tools
from ..features.agent_tools import final_answer, structured_final_answer
from ..features.issue_tracker import log_issue
from ..state import AgentState, get_dependency_context
from ..worker import build_worker_prompt, extract_artifacts, normalize_tool_result

MAX_RETRIES = 2
MAX_ITERATIONS = 15


async def execute(
    state: AgentState,
    llm: Any,
    tools: list,
    workers: dict,
    artifact_extensions: list[str],
    logger: Any = None,
    notebook: Any = None,
    issue_tracking: bool = True,
    structured_worker_output: bool = True,
    recorder: Any = None,
    tool_sources: dict | None = None,
) -> dict:
    plan = state["plan"]
    step_id = state["current_step_id"]
    for step in plan["steps"]:
        if step["id"] == step_id:
            break
    else:
        raise RuntimeError(f"Current step not found: {step_id}")

    context, artifacts = get_dependency_context(plan, step_id)
    output_dir = state["output_dir"]
    previous_attempts = step.get("attempts", [])
    worker_tools = _build_worker_tools(
        tools,
        step["worker_type"],
        output_dir,
        issue_tracking,
        structured_worker_output,
    )

    prompt = workers[step["worker_type"]]
    if structured_worker_output:
        prompt += (
            "\n\nCompletion requirement: call structured_final_answer exactly once when done. "
            "Use artifacts for files created or used, observations for short factual outputs, "
            "limitations for failures, missing data, or uncertainty, and claims/evidence for factual results."
        )

    task = build_worker_prompt(
        step["description"],
        output_dir,
        artifacts,
        context,
        previous_attempts,
        plan.get("research_context"),
    )
    messages = [SystemMessage(content=prompt), HumanMessage(content=task)]
    model = llm.bind_tools(worker_tools)

    output_parts: list[str] = []
    tool_calls_made: list[str] = []
    new_artifacts = list(artifacts)
    solution = ""
    error = None
    final_answer_produced = False
    structured_output = None
    issue_logs = []

    for _ in range(MAX_ITERATIONS):
        if logger:
            logger.thinking()
        try:
            response = await model.ainvoke(messages)
        except Exception as exc:
            error = f"Model error: {exc}"
            break

        messages.append(response)
        if logger and response.content:
            logger.thought(response.content)

        if not response.tool_calls:
            solution = response.content or ""
            break

        for tool_call in response.tool_calls:
            name = tool_call["name"]
            args = tool_call["args"]
            tool_call_id = tool_call["id"]

            if name in {"final_answer", "structured_final_answer"}:
                valid, completion, structured_output = _handle_completion_tool(name, args, worker_tools)
                messages.append(ToolMessage(content=completion, tool_call_id=tool_call_id))
                tool_calls_made.append(name)
                artifact_paths = structured_output.get("artifacts", []) if structured_output else []
                if recorder:
                    recorder.tool_call(step, name, args, completion, artifact_paths, _tool_source(tool_sources, name))
                if valid:
                    final_answer_produced = True
                    solution = completion
                    if structured_output:
                        new_artifacts.extend(structured_output.get("artifacts", []))
                else:
                    output_parts.append(f"[{name}]: {completion}")
                break

            tool_fn = _find_tool(worker_tools, name)
            if not tool_fn:
                result_str = f"Error: Tool '{name}' not found"
            else:
                if logger:
                    logger.tool_start(name, args)
                result_str = await _call_tool(tool_fn, args)

            artifact_paths = extract_artifacts(result_str, artifact_extensions)
            tool_calls_made.append(name)
            output_parts.append(f"[{name}]: {result_str[:500]}")
            new_artifacts.extend(artifact_paths)
            if result_str.startswith("ISSUE_LOGGED:"):
                issue_logs.append(result_str)
            messages.append(ToolMessage(content=result_str, tool_call_id=tool_call_id))
            if recorder:
                recorder.tool_call(step, name, args, result_str, artifact_paths, _tool_source(tool_sources, name))

            if logger:
                logger.tool_call(name, args, result_str)
            if notebook and name not in {"final_answer", "log_issue"}:
                notebook.tool_call(name, args, result_str, step["worker_type"])

        if solution:
            break

    output = "\n\n".join(output_parts)
    if solution:
        output = f"{output}\n\n## Answer\n{solution}" if output else f"## Answer\n{solution}"

    attempts = previous_attempts + [{"output": output, "error": error, "tool_calls": tool_calls_made}]
    status, error, solution = _status_from_solution(solution, error, attempts, structured_worker_output)
    new_steps = _update_steps(
        plan,
        step_id,
        status,
        output,
        solution,
        new_artifacts,
        error,
        attempts,
        final_answer_produced,
        structured_output,
    )

    update = {
        "plan": {**plan, "steps": new_steps},
        "current_step_id": None,
        "messages": [AIMessage(content=f"{status.title()}: {step['name']}")],
    }
    if issue_logs:
        update["tool_issues"] = issue_logs
    return update


def _find_tool(tools: list, name: str):
    return next((tool for tool in tools if tool.name == name), None)


def _tool_source(tool_sources: dict | None, name: str) -> dict | None:
    return tool_sources.get(name) if tool_sources else None


async def _call_tool(tool_fn, args: dict) -> str:
    try:
        result = await tool_fn.ainvoke(args)
    except NotImplementedError:
        result = tool_fn.invoke(args)
    except Exception as exc:
        result = f"Error: {type(exc).__name__}: {exc}\n\nAnalyze this error and retry with corrected parameters."
    return normalize_tool_result(result)


def _handle_completion_tool(name: str, args: dict, tools: list) -> tuple[bool, str, dict | None]:
    tool_fn = _find_tool(tools, name)
    if not tool_fn:
        return False, f"Error: {name} tool not found", None

    raw_result = tool_fn.invoke(args)
    if name == "final_answer":
        result = normalize_tool_result(raw_result)
        return (not result.startswith("Error:"), result, None)

    if isinstance(raw_result, dict) and not raw_result.get("error"):
        result = f"{raw_result['status']}: {raw_result['summary']}"
        return True, result, raw_result

    if isinstance(raw_result, dict):
        return False, raw_result.get("error", json.dumps(raw_result)), None
    return False, normalize_tool_result(raw_result), None


def _status_from_solution(solution: str, error: str | None, attempts: list[dict], structured_worker_output: bool):
    if solution.startswith("failed:"):
        return "failed", solution.strip(), ""
    if solution.startswith("success:"):
        return "completed", None, solution
    if solution:
        completion_tool = "structured_final_answer" if structured_worker_output else "final_answer"
        error = f"Call {completion_tool} to complete the task."
        status = "ready" if len(attempts) < MAX_RETRIES else "failed"
        return status, error, solution
    return "failed", error or "No solution produced", solution


def _update_steps(
    plan,
    step_id,
    status,
    output,
    solution,
    artifacts,
    error,
    attempts,
    final_answer_produced=False,
    structured_output=None,
):
    new_steps = []
    for step in plan["steps"]:
        if step["id"] == step_id:
            new_steps.append({
                **step,
                "status": status,
                "output": output,
                "solution": solution,
                "artifacts": artifacts,
                "error": error if status == "failed" else None,
                "attempts": attempts,
                "final_answer_produced": final_answer_produced,
                "structured_output": structured_output,
            })
        else:
            new_steps.append(step.copy())

    if status == "completed":
        completed = {step["id"] for step in new_steps if step["status"] == "completed"}
        for index, step in enumerate(new_steps):
            if step["status"] == "pending" and all(dep in completed for dep in step["depends_on"]):
                new_steps[index] = {**step, "status": "ready"}

    return new_steps


def _build_worker_tools(
    base_tools: list,
    worker_type: str,
    output_dir: str,
    issue_tracking: bool,
    structured_output: bool,
) -> list:
    tools = list(base_tools)
    tools.append(structured_final_answer if structured_output else final_answer)
    if issue_tracking:
        tools.append(log_issue)
    tools.extend(get_worker_tools(worker_type, output_dir, tools))
    return tools
