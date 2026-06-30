import json
import time
from typing import Any, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..config import WORKER_TOOLS
from ..state import AgentState, get_dependency_context
from ..worker import build_worker_prompt, extract_artifacts, normalize_tool_result
from ..features.agent_tools import final_answer, structured_final_answer
from ..features.issue_tracker import log_issue
from ..features.run_local_tools import get_run_local_tools

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
    issue_tracking: bool = True,
    structured_worker_output: bool = False,
    run_local_tool_prototyping: bool = False,
    role_prompts: bool = True,
    diagnostics: Any = None,
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
    agent_name = f"{step['worker_type']}_worker"

    worker_tools = _build_worker_tools(
        tools,
        step["worker_type"],
        issue_tracking,
        structured_worker_output,
        run_local_tool_prototyping,
    )
    if diagnostics:
        diagnostics.assign_step(agent_name, step_id, [t.name for t in worker_tools])

    if role_prompts:
        prompt = workers.get(step["worker_type"]) or workers.get("data", "")
    else:
        prompt = f"You are the {step['worker_type']} worker."
    if structured_worker_output:
        prompt += (
            "\n\nCompletion requirement: call structured_final_answer exactly once when done. "
            "Use artifacts for files created or used, observations for short factual outputs, "
            "and limitations for failures, missing data, or uncertainty."
        )
    task = build_worker_prompt(step["description"], output_dir, artifacts, context, previous_attempts, research_context, lessons)

    model = llm.bind_tools(worker_tools)
    messages = [SystemMessage(content=prompt), HumanMessage(content=task)]
    output_parts, tool_calls_made, new_artifacts = [], [], list(artifacts)
    solution, error = "", None
    final_answer_produced = False
    structured_output = None
    structured_output_valid = None

    for iteration in range(MAX_ITERATIONS):
        if logger:
            logger.thinking()
        try:
            if diagnostics:
                response = await diagnostics.record_llm_call(
                    agent_name,
                    "worker_iteration",
                    llm,
                    messages,
                    "not_applicable",
                    lambda: model.ainvoke(messages),
                )
            else:
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
                final_answer_produced = True
                solution = f"{args.get('status', 'success')}: {args.get('summary', '')}"
                messages.append(ToolMessage(content=solution, tool_call_id=tc_id))
                break
            if name == "structured_final_answer":
                final_answer_produced = True
                tool_fn = next((t for t in worker_tools if t.name == name), None)
                raw_result = tool_fn.invoke(args) if tool_fn else {"error": "structured_final_answer tool not found"}
                structured_output_valid = isinstance(raw_result, dict) and not raw_result.get("error")
                if structured_output_valid:
                    structured_output = raw_result
                    solution = f"{raw_result['status']}: {raw_result['summary']}"
                    new_artifacts.extend(raw_result.get("artifacts", []))
                else:
                    solution = ""
                    result_error = raw_result.get("error") if isinstance(raw_result, dict) else str(raw_result)
                    messages.append(ToolMessage(content=result_error, tool_call_id=tc_id))
                    if diagnostics:
                        diagnostics.failure("llm_instruction_failure", agent_name, step_id, f"Invalid structured_final_answer: {result_error}", False, "invalid_worker_output")
                    break
                result_str = json.dumps(raw_result)
                messages.append(ToolMessage(content=result_str, tool_call_id=tc_id))
                if diagnostics:
                    diagnostics.record_worker_output(agent_name, step_id, raw_result, structured_output_valid)
                break

            tool_fn = next((t for t in worker_tools if t.name == name), None)
            tool_started = time.perf_counter()
            tool_status = "success"
            error_type = None
            error_message = None
            if not tool_fn:
                result_str = f"Tool '{name}' not found"
                tool_status = "failed"
                error_type = "llm_tool_hallucination"
                error_message = result_str
            else:
                if logger:
                    logger.tool_start(name, args)
                try:
                    result = await tool_fn.ainvoke(args)
                except NotImplementedError:
                    result = tool_fn.invoke(args)
                except Exception as e:
                    result = f"ERROR: {e}\n\nAnalyze this error and retry with corrected parameters."
                    tool_status = "failed"
                    error_message = str(e)
                    error_type = _classify_tool_error(e)
                result_str = normalize_tool_result(result)

            tool_calls_made.append(name)
            output_parts.append(f"[{name}]: {result_str[:500]}")
            detected_artifacts = extract_artifacts(result_str, artifact_extensions)
            new_artifacts.extend(detected_artifacts)
            messages.append(ToolMessage(content=result_str, tool_call_id=tc_id))
            if diagnostics:
                diagnostics.record_tool_call(
                    agent_name,
                    step_id,
                    name,
                    _tool_source(name, tools, diagnostics),
                    time.perf_counter() - tool_started,
                    tool_status,
                    error_type,
                    error_message,
                    detected_artifacts,
                )
                if tool_status == "failed" and error_type:
                    impact = "unknown_tool_requested" if error_type == "llm_tool_hallucination" else "tool_call_failed"
                    diagnostics.failure(error_type, agent_name, step_id, error_message or result_str, False, impact)

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
        if structured_worker_output:
            error = "Call structured_final_answer(status, summary, artifacts, observations, limitations) to complete."
        status = "ready" if len(attempts) < MAX_RETRIES else "failed"
    else:
        status, error = "failed", error or "No solution produced"

    if not final_answer_produced and diagnostics:
        diagnostics.failure("llm_instruction_failure", agent_name, step_id, "Worker did not call the required final answer tool.", status != "failed", "missing_final_answer")
    if structured_worker_output and final_answer_produced and structured_output_valid is not True and diagnostics:
        diagnostics.record_worker_output(agent_name, step_id, structured_output or {"status": None, "summary": None}, False)
    if status == "completed" and diagnostics:
        diagnostics.mark_step_recovered(agent_name, step_id)

    new_steps = _update_steps(plan, step_id, status, output, solution, new_artifacts, error, attempts, final_answer_produced, structured_output)
    return {
        "plan": {**plan, "steps": new_steps},
        "current_step_id": None,
        "messages": [AIMessage(content=f"{'Completed' if status == 'completed' else 'Failed' if status == 'failed' else 'Retrying'}: {step['name']}")],
    }


def _update_steps(plan, step_id, status, output, solution, artifacts, error, attempts, final_answer_produced=False, structured_output=None):
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
                "final_answer_produced": final_answer_produced,
                "structured_output": structured_output,
            })
        else:
            new_steps.append(s.copy())

    if status == "completed":
        completed = {s["id"] for s in new_steps if s["status"] == "completed"}
        for i, s in enumerate(new_steps):
            if s["status"] == "pending" and all(dep in completed for dep in s["depends_on"]):
                new_steps[i] = {**s, "status": "ready"}

    return new_steps


def _build_worker_tools(base_tools: List, worker_type: str, issue_tracking: bool, structured_output: bool, run_local_tools: bool) -> List:
    tools = list(base_tools)
    tools.append(structured_final_answer if structured_output else final_answer)
    if issue_tracking:
        tools.append(log_issue)
    if worker_type in WORKER_TOOLS:
        tools.extend(WORKER_TOOLS[worker_type]())
    if run_local_tools and worker_type == "compute":
        tools.extend(get_run_local_tools())
    return tools


def _classify_tool_error(error: Exception) -> str:
    name = type(error).__name__.lower()
    text = str(error).lower()
    if any(term in name or term in text for term in ("validation", "argument", "schema", "pydantic", "missing required")):
        return "tool_argument_failure"
    if any(term in text for term in ("connection", "timeout", "http", "api", "server")):
        return "remote_api_failure"
    return "tool_runtime_failure"


def _tool_source(name: str, mcp_tools: List, diagnostics: Any = None) -> str:
    if diagnostics:
        for tool in diagnostics.data.get("configuration", {}).get("available_tools", []):
            if tool.get("name") == name:
                return tool.get("source") or "mcp"
    if any(getattr(t, "name", None) == name for t in mcp_tools):
        return "mcp"
    return "built_in"
