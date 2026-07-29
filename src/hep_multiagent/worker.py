import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage


def format_attempts(attempts: list[dict]) -> str:
    if not attempts:
        return ""
    parts = [f"## Attempt {i}\n{a.get('output', '')}\n{a.get('error', '')}" for i, a in enumerate(attempts, 1)]
    return "# Previous Attempts\n" + "\n".join(parts) + "\n\nAnalyze what went wrong and try a different approach."


def extract_artifacts(text: str, extensions: list[str]) -> list[str]:
    artifacts = []
    for ext in extensions:
        pattern = r'[\w/.-]+' + ext.replace('.', r'\.')
        artifacts.extend(re.findall(pattern, text))
    return list(set(artifacts))


def normalize_tool_result(result) -> str:
    if result is None:
        return ""
    if getattr(result, "status", None) == "error":
        return f"Error: {getattr(result, 'content', result)}"
    if hasattr(result, "content"):
        return str(result.content)
    if isinstance(result, list):
        return "\n".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in result)
    if isinstance(result, dict) and result.get("type") == "text":
        return result.get("text", "")
    return str(result)


async def _invoke_tool(tools: list, name: str, args: dict) -> str:
    for tool in tools:
        if tool.name == name:
            try:
                result = await tool.ainvoke(args)
            except NotImplementedError:
                result = tool.invoke(args)
            except Exception as e:
                return f"Error: {e}"
            return normalize_tool_result(result)
    return f"Error: Tool '{name}' not found"


def build_worker_prompt(
    task: str,
    output_dir: str,
    artifacts: list[str],
    context: str,
    previous_attempts: list[dict],
    research_context: str | None = None,
) -> str:
    parts = [
        f"# Task\n{task}",
        f"# Output Directory\nSave files to exactly this directory: {output_dir}\nIf a tool has an output_dir parameter, pass this exact path.",
    ]
    if research_context:
        parts.append(f"# Research Context (already gathered - use directly)\n{research_context}")
    if artifacts:
        parts.append("# Available Files\n" + "\n".join(artifacts))
    if context:
        parts.append(f"# Prior Results\n{context}")
    if previous_attempts:
        parts.append(format_attempts(previous_attempts))
    parts.append("# Instructions\nUse tools to complete this task. If you reference papers, you MUST cite them using cite(). Provide a clear answer when done.")
    return "\n\n".join(parts)


async def run_consultation(
    llm: Any,
    tools: list,
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
