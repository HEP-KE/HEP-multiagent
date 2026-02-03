import re
from typing import List, Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage


def extract_artifacts(text: str, extensions: List[str]) -> List[str]:
    artifacts = []
    for ext in extensions:
        pattern = r'[\w/.-]+' + ext.replace('.', r'\.')
        artifacts.extend(re.findall(pattern, text))
    return list(set(artifacts))


def normalize_tool_result(result) -> str:
    if result is None:
        return ""
    if isinstance(result, list):
        return "\n".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in result)
    if isinstance(result, dict) and result.get("type") == "text":
        return result.get("text", "")
    return str(result)


async def _invoke_tool(tools: List, name: str, args: dict) -> str:
    for tool in tools:
        if tool.name == name:
            try:
                result = await tool.ainvoke(args)
            except NotImplementedError:
                result = tool.invoke(args)
            except Exception as e:
                return f"Error: {e}"
            return normalize_tool_result(result)
    return f"Tool '{name}' not found"


def build_worker_prompt(
    task: str,
    output_dir: str,
    artifacts: List[str],
    context: str,
    previous_attempts: List[dict],
    research_context: str = None,
) -> str:
    parts = [f"# Task\n{task}", f"# Output Directory\nSave files to: {output_dir}"]
    if research_context:
        parts.append(f"# Research Context (already gathered - use directly)\n{research_context}")
    if artifacts:
        parts.append("# Available Files\n" + "\n".join(artifacts))
    if context:
        parts.append(f"# Prior Results\n{context}")
    if previous_attempts:
        attempt_lines = ["# Previous Attempts"]
        for i, att in enumerate(previous_attempts, 1):
            attempt_lines.append(f"Attempt {i}: " +
                (f"Error: {att['error']}" if att.get("error") else "") +
                (f"Tools: {', '.join(att['tool_calls'])}" if att.get("tool_calls") else ""))
        attempt_lines.append("Try a different approach.")
        parts.append("\n".join(attempt_lines))
    parts.append("# Instructions\nUse tools to complete this task. If you reference papers, you MUST cite them using cite(). Provide a clear answer when done.")
    return "\n\n".join(parts)


def build_worker_result(
    output_parts: List[str],
    solution: str,
    artifacts: List[str],
    error: str,
    tool_calls: List[str],
) -> dict:
    output = "\n\n".join(output_parts)
    if solution:
        output += f"\n\n## Answer\n{solution}"
    return {
        "output": output,
        "solution": solution,
        "artifacts": list(set(artifacts)),
        "error": error,
        "attempt": {"output": output[:1000], "error": error, "tool_calls": tool_calls},
    }


async def run_consultation(
    llm: Any,
    tools: List,
    prompt: str,
    question: str,
    max_iterations: int = 10,
) -> str:
    if not tools:
        return "No tools available."
    model = llm.bind_tools(tools)
    messages = [SystemMessage(content=prompt), HumanMessage(content=question)]
    for _ in range(max_iterations):
        response = await model.ainvoke(messages)
        if response.tool_calls:
            messages.append(response)
            for tc in response.tool_calls:
                result = await _invoke_tool(tools, tc["name"], tc["args"])
                messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        else:
            return response.content or ""
    return "Max iterations reached."


async def run_worker_async(
    llm: Any,
    tools: List,
    prompt: str,
    task: str,
    context: str,
    artifacts: List[str],
    previous_attempts: List[dict],
    output_dir: str,
    artifact_extensions: List[str],
    max_iterations: int = 25,
    logger: Any = None,
    notebook: Any = None,
    worker_type: str = None,
) -> dict:
    model = llm.bind_tools(tools)
    full_prompt = build_worker_prompt(task, output_dir, artifacts, context, previous_attempts)
    messages = [SystemMessage(content=prompt), HumanMessage(content=full_prompt)]

    output_parts = []
    tool_calls_made = []
    solution = ""
    new_artifacts = list(artifacts)
    error = None

    for iteration in range(max_iterations):
        if logger:
            logger.iteration(iteration + 1, max_iterations)

        try:
            response = await model.ainvoke(messages)
        except Exception as e:
            error = f"Model error: {e}"
            break

        messages.append(response)

        if logger and response.content:
            logger.thought(response.content)

        if response.tool_calls:
            for tc in response.tool_calls:
                result_str = await _invoke_tool(tools, tc["name"], tc["args"])
                tool_calls_made.append(tc["name"])
                output_parts.append(f"[{tc['name']}]: {result_str[:500]}")
                new_artifacts.extend(extract_artifacts(result_str, artifact_extensions))
                messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
                if logger:
                    logger.tool_call(tc["name"], tc["args"], result_str)
                if notebook:
                    notebook.tool_call(tc["name"], tc["args"], result_str, worker_type)
        else:
            solution = response.content
            break
    else:
        # Loop completed without break = max iterations reached
        error = f"Max iterations ({max_iterations}) reached without completion"

    return build_worker_result(output_parts, solution, new_artifacts, error, tool_calls_made)
