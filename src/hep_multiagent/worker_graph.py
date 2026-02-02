from typing import TypedDict, List, Literal, Annotated
from operator import add

from langchain_core.messages import ToolMessage
from langgraph.graph import StateGraph, START, END


class WorkerState(TypedDict, total=False):
    messages: Annotated[List, add]
    pending_tools: List[dict]
    tool_index: int
    iteration: int
    max_iterations: int
    solution: str
    error: str
    outputs: Annotated[List[str], add]
    artifacts: List[str]


def call_model(state: WorkerState, model) -> dict:
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 25)

    if iteration >= max_iter:
        return {"error": f"Max iterations ({max_iter}) reached"}

    response = model.invoke(state.get("messages", []))

    pending = [{"id": tc["id"], "name": tc["name"], "args": tc["args"]} for tc in (response.tool_calls or [])]
    solution = response.content if not pending and response.content else None

    return {
        "messages": [response],
        "pending_tools": pending,
        "tool_index": 0,
        "solution": solution,
        "iteration": iteration + 1,
    }


def execute_tool(state: WorkerState, tools, extensions, logger=None, notebook=None, worker_type=None) -> dict:
    from .worker import extract_artifacts, normalize_tool_result
    import asyncio

    pending = state.get("pending_tools", [])
    idx = state.get("tool_index", 0)
    if idx >= len(pending):
        return {}

    tc = pending[idx]
    name, args = tc["name"], tc["args"]

    result = f"Tool '{name}' not found"
    for tool in tools:
        if tool.name == name:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
            result = normalize_tool_result(loop.run_until_complete(tool.ainvoke(args)))
            break

    if logger:
        logger.tool_call(name, args, result)
    if notebook:
        notebook.tool_call(name, args, result, worker_type)

    return {
        "messages": [ToolMessage(content=result, tool_call_id=tc["id"])],
        "outputs": [f"[{name}]: {result[:500]}"],
        "tool_index": idx + 1,
        "artifacts": state.get("artifacts", []) + extract_artifacts(result, extensions),
    }


def route(state: WorkerState) -> Literal["done", "model", "tool"]:
    if state.get("error") or state.get("solution"):
        return "done"
    if state.get("tool_index", 0) >= len(state.get("pending_tools", [])):
        return "model"
    return "tool"


def build(llm, tools, extensions, logger=None, notebook=None, worker_type=None):
    model = llm.bind_tools(tools)

    graph = StateGraph(WorkerState)
    graph.add_node("model", lambda s: call_model(s, model))
    graph.add_node("tool", lambda s: execute_tool(s, tools, extensions, logger, notebook, worker_type))

    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route, {"done": END, "model": "model", "tool": "tool"})
    graph.add_conditional_edges("tool", route, {"done": END, "model": "model", "tool": "tool"})

    return graph.compile()
