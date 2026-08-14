import os
import re
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..state import AgentState, Plan
from ..config import CONSULTANTS
from ..workers.research import get_research_tools


PROMPT = """You are a planning agent for scientific data analysis.

Use the consultation context if it appears below. Put specific facts, file names,
tool names, thresholds, and constraints directly into the step descriptions.
Do not create a step to rediscover information that is already in context.
Create research steps only when the final answer needs cited papers.

{context}

## Available Workers

{worker_docs}

{tool_docs}

{research_instruction}

## Output Format

Return a structured plan only. Do not call tools, answer the user query, or
write tool-call text. Use worker_type values from: {worker_type_options}.

"""


class PlanStepOutput(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    worker_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    goal: str = Field(min_length=1)
    steps: list[PlanStepOutput] = Field(min_length=1)

VAGUE_TERMS = [
    "interesting", "unusual", "significant", "important", "relevant",
    "recent", "old", "large", "small", "massive", "best", "worst",
    "good", "bad", "typical", "atypical", "normal", "abnormal",
    "extreme", "moderate",
]

def detect_vague_terms(query: str) -> list[str]:
    return [t for t in VAGUE_TERMS if re.search(rf"\b{t}\b", query.lower())]


def extract_file_paths(query: str) -> list[str]:
    pattern = r'["\']?([^\s"\']+\.(?:hdf5|h5|fits|csv|txt|dat|npy|npz|json|yaml|yml))["\']?'
    return list(dict.fromkeys(re.findall(pattern, query, re.IGNORECASE)))


def _check_output_dir_files(output_dir: str) -> bool:
    if not os.path.exists(output_dir):
        return False
    data_exts = {'.hdf5', '.h5', '.fits', '.csv', '.npy', '.npz', '.json', '.dat'}
    for f in os.listdir(output_dir):
        if os.path.splitext(f)[1].lower() in data_exts:
            return True
    return False


def _is_research_only_query(query: str) -> bool:
    q = query.lower()
    research_terms = ['arxiv', 'paper', 'literature', 'publication', 'cite', 'research']
    data_terms = ['load', 'fetch', 'data', 'catalog', 'halo', 'galaxy', 'simulation', 'plot', 'chart', 'histogram', 'compute', 'calculate', 'analyze', 'filter']
    has_research = any(t in q for t in research_terms)
    has_data = any(t in q for t in data_terms)
    return has_research and not has_data


def validate_plan_data(plan_data: Any, worker_types: tuple[str, ...]) -> None:
    if not isinstance(plan_data, dict):
        raise ValueError("Plan must be a JSON object")
    if not isinstance(plan_data.get("goal"), str) or not plan_data["goal"].strip():
        raise ValueError("Plan goal must be a non-empty string")
    if not isinstance(plan_data.get("steps"), list) or not plan_data["steps"]:
        raise ValueError("Plan steps must be a non-empty list")

    seen = set()
    for index, step in enumerate(plan_data["steps"], 1):
        if not isinstance(step, dict):
            raise ValueError(f"Step {index} must be a JSON object")
        for key in ("id", "name", "worker_type", "description"):
            if not isinstance(step.get(key), str) or not step[key].strip():
                raise ValueError(f"Step {index} missing non-empty '{key}'")

        step_id = step["id"]
        if step_id in seen:
            raise ValueError(f"Duplicate step id: {step_id}")
        if step["worker_type"] not in worker_types:
            raise ValueError(f"Unknown worker_type for step {step_id}: {step['worker_type']}")

        depends_on = step.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(isinstance(dep, str) for dep in depends_on):
            raise ValueError(f"Step {step_id} depends_on must be a list of step ids")
        missing = [dep for dep in depends_on if dep not in seen]
        if missing:
            raise ValueError(f"Step {step_id} depends on unknown or later step id(s): {', '.join(missing)}")
        seen.add(step_id)


async def plan(
    state: AgentState,
    llm: Any,
    tools: list,
    worker_docs: str,
    logger=None,
    planner_consultations: bool = False,
    worker_types: tuple[str, ...] = ("data", "compute", "research", "viz"),
) -> dict:
    tool_docs_str = "\n".join(f"- {t.name}: {t.description}" for t in tools)

    query = ""
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            query = msg.content
            break

    files = extract_file_paths(query)
    output_dir = state["output_dir"]
    has_mcp_tools = len(tools) > 0
    has_local_files = files or _check_output_dir_files(output_dir)
    is_research_only = _is_research_only_query(query)

    if not is_research_only and not has_mcp_tools and not has_local_files:
        msg = "Cannot fulfill this query: No data files in output directory and no MCP tools available to fetch data."
        if logger:
            logger.log("Planner", msg)
        return {"plan": None, "error": msg}

    context_parts = []
    consultation_parts = []
    arxiv_consulted = False

    vague = detect_vague_terms(query)

    if planner_consultations:
        if vague:
            if logger:
                logger.log("Arxiv Consultant", f"Input: query=\"{query}\", vague_terms={vague}")
            result = await CONSULTANTS["arxiv"].consult(llm, get_research_tools(), query)
            if logger:
                logger.log("Arxiv Consultant", f"Output:\n{result}")
            consultation_parts.append(f"## Research Results (already completed - DO NOT re-research)\n{result}")
            arxiv_consulted = True

        for path in files:
            if logger:
                logger.log("File Consultant", f"Input: path=\"{path}\"")
            result = await CONSULTANTS["file"].consult(llm, tools, f"Describe columns and structure of {path}")
            if logger:
                logger.log("File Consultant", f"Output:\n{result}")
            consultation_parts.append(f"## File: {path}\n{result}")

        if not files and not arxiv_consulted and tools:
            tool_doc_list = []
            for t in tools:
                if isinstance(t.args_schema, dict):
                    schema = t.args_schema
                elif t.args_schema and hasattr(t.args_schema, "model_json_schema"):
                    schema = t.args_schema.model_json_schema()
                else:
                    schema = t.args_schema.schema() if t.args_schema else {}
                params = schema.get("properties", {})
                param_str = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in params.items())
                tool_doc_list.append(f"- {t.name}({param_str}): {t.description}")
            question = f"What data sources are available for: {query}\n\nAvailable tools:\n" + "\n".join(tool_doc_list)
            if logger:
                logger.log("Data Consultant", f"Input: query=\"{query}\", tools={len(tools)}")
            result = await CONSULTANTS["data"].consult(llm, tools, question)
            if logger:
                logger.log("Data Consultant", f"Output:\n{result}")
            consultation_parts.append(f"## Available Data\n{result}")

    consultation_context = "\n\n".join(consultation_parts)
    if consultation_context:
        context_parts.append(consultation_context)

    context = "\n".join(context_parts) if context_parts else ""

    research_instruction = ""
    needs_citations = any(term in query.lower() for term in ["cite", "paper", "reference", "literature", "arxiv", "publication"])
    if arxiv_consulted and "research" in worker_types:
        if needs_citations:
            research_instruction = """## MANDATORY: Research Worker Required

The query mentions papers/arxiv. You MUST include a research worker step.

The consultation above found papers but they are NOT YET CITED. The research worker MUST:
1. Search for the papers mentioned above using search_arxiv_abstracts
2. Call cite() for each paper to add them to references.bib
3. This ensures proper citations [arXiv:XXXX.XXXXX] appear in the final report

REQUIRED STEP (add this to your plan):
{
    "id": "sN",
    "name": "cite_papers",
    "worker_type": "research",
    "description": "Search arxiv for the papers found during consultation and cite them using cite() to build references.bib. Papers to cite: [list arXiv IDs from consultation above]",
    "depends_on": []
}

Then embed the scientific CRITERIA from consultation into compute/viz step descriptions."""
        else:
            research_instruction = """## Research Context Available
The consultation above found criteria for your query.
- Do NOT create research worker steps (no citations needed for this query)
- EMBED the specific values and thresholds directly into compute/viz step descriptions
- Example: Instead of "find interesting halos", write "filter where mass > 1e14 OR entropy < 30" """

    prompt = PROMPT.format(
        worker_docs=worker_docs,
        worker_type_options="|".join(worker_types),
        tool_docs=f"Available tools:\n{tool_docs_str}" if tool_docs_str else "",
        context=context,
        research_instruction=research_instruction,
    )

    if logger:
        logger.log("Planner", "Generating plan from LLM...")
    messages = [SystemMessage(content=prompt), HumanMessage(content=query)]
    try:
        plan_output = await llm.with_structured_output(PlanOutput).ainvoke(messages)
    except Exception as e:
        return {"plan": None, "error": f"Planner structured output failed: {type(e).__name__}: {e}"}

    plan_data = plan_output.model_dump()
    if logger:
        logger.log("Planner", f"Structured plan:\n{plan_output.model_dump_json(indent=2)}")

    try:
        validate_plan_data(plan_data, worker_types)
    except ValueError as e:
        return {"plan": None, "error": f"Invalid plan: {e}"}

    result: Plan = {
        "id": str(uuid.uuid4()),
        "goal": plan_data["goal"],
        "status": "active",
        "steps": [],
        "research_context": consultation_context if arxiv_consulted else None,
    }

    for step in plan_data["steps"]:
        result["steps"].append({
            "id": step["id"],
            "name": step["name"],
            "worker_type": step["worker_type"],
            "description": step["description"],
            "depends_on": step.get("depends_on", []),
            "status": "ready" if not step.get("depends_on") else "pending",
            "output": None,
            "solution": None,
            "artifacts": [],
            "error": None,
            "attempts": [],
            "final_answer_produced": False,
            "structured_output": None,
        })

    return {"plan": result}
