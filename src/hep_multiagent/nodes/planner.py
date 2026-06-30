import json
import os
import re
import uuid
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import AgentState, Plan
from ..config import CONSULTANTS
from ..workers.research import get_research_tools


PROMPT = """You are a planning agent for scientific data analysis.

You MUST consult specialist agents to gather information BEFORE creating your plan.

## Your Consultation Tools

The system has already consulted specialists if context appears below. Use that information.

## CRITICAL: How Consultation Works

When consultation happens, you receive information NOW. You must EMBED that information directly into your plan descriptions.

WRONG approach:
- Consultation found papers about "interesting halos"
- Create a plan step: "research_interest_criteria: Use research worker to find what makes halos interesting"
- This is WRONG because the research is already done!

CORRECT approach:
- Consultation found: "Massive halos (M500c > 1e14), cool-core clusters (K0 < 30 keV cm²)"
- Create a plan step: "filter_interesting: Filter halos where sod_halo_M500c > 1e14 OR sod_halo_core_entropy < 30"
- The specific criteria from consultation are embedded in the step description

## Your Process

1. IDENTIFY what's known from consultation context above
2. EMBED specific values, thresholds, column names into step descriptions
3. Do NOT create research steps to re-research what's already in context
4. ONLY create research steps if papers need CITATIONS in the final report

{context}

## Available Workers

{worker_docs}

{tool_docs}

- **data**: Fetch remote data via MCP tools
- **compute**: Load files, filter, transform, compute statistics, save results
- **research**: Search arxiv AND cite papers. Use ONLY when papers must appear with citations in the final report.
- **viz**: Create plots and visualizations

{research_instruction}

## Output Format

```json
{{
    "goal": "summary including the specific criteria you determined from consultation",
    "steps": [
        {{
            "id": "s1",
            "name": "step_name",
            "worker_type": "data|compute|research|viz",
            "description": "Detailed instructions with SPECIFIC values from consultation",
            "depends_on": []
        }}
    ]
}}
```

## Example

Query: "Find interesting halos in data.hdf5"

Consultation found:
- Columns: sod_halo_mass, sod_halo_cdelta, sod_halo_core_entropy, fof_halo_tag...
- Interesting criteria: Massive (M > 1e14), Cool-core (entropy < 30), Concentration outliers (cdelta > 2σ)

Plan (NO research steps - consultation already done):
```json
{{
    "goal": "Find interesting halos using criteria: mass>1e14, entropy<30, concentration outliers",
    "steps": [
        {{"id": "s1", "name": "load_data", "worker_type": "compute", "description": "Load data.hdf5", "depends_on": []}},
        {{"id": "s2", "name": "filter_interesting", "worker_type": "compute", "description": "Filter where sod_halo_mass > 1e14 OR sod_halo_core_entropy < 30 OR abs(sod_halo_cdelta - mean) > 2*std", "depends_on": ["s1"]}}
    ]
}}
```
"""

MINIMAL_PROMPT = """Create an execution plan for the user query.

Available workers: {worker_docs}

{tool_docs}

Return JSON with this shape:
{{
  "goal": "short goal",
  "steps": [
    {{
      "id": "s1",
      "name": "step_name",
      "worker_type": "data|compute|research|viz",
      "description": "specific task",
      "depends_on": []
    }}
  ]
}}
"""

VAGUE_TERMS = [
    "interesting", "unusual", "significant", "important", "relevant",
    "recent", "old", "large", "small", "massive", "best", "worst",
    "good", "bad", "typical", "atypical", "normal", "abnormal",
    "extreme", "moderate",
]


def detect_vague_terms(query: str) -> List[str]:
    return [t for t in VAGUE_TERMS if re.search(rf"\b{t}\b", query.lower())]


def extract_file_paths(query: str) -> List[str]:
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


def extract_json(text: str) -> Optional[str]:
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            return text[start:end].strip()
    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start and text[start:end].strip().startswith("{"):
            return text[start:end].strip()
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return json.dumps(obj)
    except json.JSONDecodeError:
        return None


async def plan(state: AgentState, llm: Any, tools: List, worker_docs: str, logger=None, diagnostics=None, role_prompts: bool = True) -> dict:
    tool_docs_str = "\n".join(f"- {t.name}: {t.description}" for t in tools)

    query = ""
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            query = msg.content
            break

    files = extract_file_paths(query)
    output_dir = state.get("output_dir", ".")
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

    if vague:
        if logger:
            logger.log("Arxiv Consultant", f"Input: query=\"{query}\", vague_terms={vague}")
        if diagnostics:
            diagnostics.event("arxiv_consultant", "started", f"Vague terms detected: {', '.join(vague)}")
        result = await CONSULTANTS["arxiv"].consult(llm, get_research_tools(), query)
        if logger:
            logger.log("Arxiv Consultant", f"Output:\n{result}")
        if diagnostics:
            diagnostics.event("arxiv_consultant", "completed", "Research consultation completed")
        consultation_parts.append(f"## Research Results (already completed - DO NOT re-research)\n{result}")
        arxiv_consulted = True

    for path in files:
        if logger:
            logger.log("File Consultant", f"Input: path=\"{path}\"")
        if diagnostics:
            diagnostics.event("file_consultant", "started", f"Inspecting {path}")
        result = await CONSULTANTS["file"].consult(llm, tools, f"Describe columns and structure of {path}")
        if logger:
            logger.log("File Consultant", f"Output:\n{result}")
        if diagnostics:
            diagnostics.event("file_consultant", "completed", f"Inspected {path}")
        consultation_parts.append(f"## File: {path}\n{result}")

    if not files and not arxiv_consulted and tools:
        tool_doc_list = []
        for t in tools:
            schema = t.args_schema if isinstance(t.args_schema, dict) else (t.args_schema.schema() if t.args_schema else {})
            params = schema.get("properties", {})
            param_str = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in params.items())
            tool_doc_list.append(f"- {t.name}({param_str}): {t.description}")
        question = f"What data sources are available for: {query}\n\nAvailable tools:\n" + "\n".join(tool_doc_list)
        if logger:
            logger.log("Data Consultant", f"Input: query=\"{query}\", tools={len(tools)}")
        if diagnostics:
            diagnostics.event("data_consultant", "started", f"Inspecting {len(tools)} available tools")
        result = await CONSULTANTS["data"].consult(llm, tools, question)
        if logger:
            logger.log("Data Consultant", f"Output:\n{result}")
        if diagnostics:
            diagnostics.event("data_consultant", "completed", "Data consultation completed")
        consultation_parts.append(f"## Available Data\n{result}")

    consultation_context = "\n\n".join(consultation_parts)
    if consultation_context:
        context_parts.append(consultation_context)

    feedback = state.get("planning_feedback")
    if feedback:
        context_parts.append(f"Previous plan was rejected. Feedback: {feedback}")

    context = "\n".join(context_parts) if context_parts else ""

    research_instruction = ""
    needs_citations = any(term in query.lower() for term in ["cite", "paper", "reference", "literature", "arxiv", "publication"])
    if arxiv_consulted:
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

    template = PROMPT if role_prompts else MINIMAL_PROMPT
    prompt = template.format(
        worker_docs=worker_docs,
        tool_docs=f"Available tools:\n{tool_docs_str}" if tool_docs_str else "",
        context=context,
        research_instruction=research_instruction,
    )

    if logger:
        logger.log("Planner", "Generating plan from LLM...")
    messages = [SystemMessage(content=prompt), HumanMessage(content=query)]
    if diagnostics:
        response = await diagnostics.record_llm_call("planner", "create_plan", llm, messages, "pending", lambda: llm.ainvoke(messages))
    else:
        response = await llm.ainvoke(messages)
    if logger and response.content:
        logger.log("Planner", f"LLM response:\n{response.content}")

    json_str = extract_json(response.content)
    if not json_str:
        if diagnostics:
            diagnostics.data["checks"]["plan_json_valid"] = False
            diagnostics.mark_last_llm_contract("planner", "create_plan", "invalid", "No JSON found in planner response")
            diagnostics.failure("llm_invalid_output", "planner", None, "No JSON found in planner response", False, "plan_not_created")
        return {"plan": None, "error": "No JSON found in planner response"}

    try:
        plan_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        if diagnostics:
            diagnostics.data["checks"]["plan_json_valid"] = False
            diagnostics.mark_last_llm_contract("planner", "create_plan", "invalid", f"JSON parse error: {e}")
            diagnostics.failure("llm_invalid_output", "planner", None, f"JSON parse error: {e}", False, "plan_not_created")
        return {"plan": None, "error": f"JSON parse error: {e}"}
    if diagnostics:
        diagnostics.data["checks"]["plan_json_valid"] = True
        diagnostics.mark_last_llm_contract("planner", "create_plan", "valid")

    result: Plan = {
        "id": str(uuid.uuid4()),
        "goal": plan_data["goal"],
        "status": "draft",
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
