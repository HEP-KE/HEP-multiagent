import json
import re
import uuid
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import AgentState, Plan
from ..config import CONSULTANTS
from ..workers.research import get_research_tools


PROMPT = """You are a planning agent. Create execution plans for data analysis tasks.

## Available Workers
{worker_docs}

{tool_docs}

{context}

## Planning Guidelines

1. **Data first**: If data needs to be fetched, that step comes first
2. **Dependencies**: Use depends_on to specify step execution order
3. **Specific instructions**: Include exact column names, thresholds, and parameters
4. **One task per step**: Each step should do one focused thing
5. **Define vague terms**: If query uses subjective words (interesting, unusual, best), define specific quantitative criteria in the step description
6. **Explicit file handoff**: When a step depends on another, specify what file to load (e.g., "Load papers.json from s1")
7. **Minimal work**: Only do what the query asks. No extra analysis, no extra files, no over-engineering

## Worker Selection

- **data**: Fetch remote data via MCP tools
- **compute**: Load files, filter, transform, compute statistics
- **research**: Search literature for definitions and methods (use BEFORE compute if criteria need definition)
- **viz**: Create plots and visualizations

## Handling Subjective Terms

If the query contains vague terms like "interesting", "unusual", or "best":
1. Add a research step FIRST to find scientific definitions/thresholds
2. Embed those specific criteria into subsequent step descriptions
3. Example: "interesting halos" → research finds M>1e14, then compute step says "filter where mass > 1e14"

## Output Format

Output ONLY valid JSON:
```json
{{
    "goal": "clear summary including specific criteria determined",
    "steps": [
        {{
            "id": "s1",
            "name": "descriptive_step_name",
            "worker_type": "data|compute|research|viz",
            "description": "Detailed instructions with specific parameters",
            "depends_on": []
        }},
        {{
            "id": "s2",
            "name": "next_step",
            "worker_type": "compute",
            "description": "Use results from s1 to...",
            "depends_on": ["s1"]
        }}
    ]
}}
```
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


async def plan(state: AgentState, llm: Any, tools: List, worker_docs: str, logger=None) -> dict:
    tool_docs = "\n".join(f"- {t.name}: {t.description}" for t in tools)

    query = ""
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            query = msg.content
            break

    context_parts = []
    consultation_parts = []

    vague = detect_vague_terms(query)
    files = extract_file_paths(query)

    if vague:
        if logger:
            logger.log("Planner", f"Detected vague terms: {vague}. Consulting arxiv...")
        result = await CONSULTANTS["arxiv"].consult(llm, get_research_tools(), query)
        if logger:
            logger.log("Planner", f"Arxiv consultation:\n{result[:500]}...")
        consultation_parts.append(f"## Research\n{result}")

    for path in files:
        if logger:
            logger.log("Planner", f"Consulting file structure: {path}")
        result = await CONSULTANTS["file"].consult(llm, tools, f"Describe columns and structure of {path}")
        if logger:
            logger.log("Planner", f"File consultation:\n{result[:500]}...")
        consultation_parts.append(f"## File: {path}\n{result}")

    if not files and tools:
        tool_docs = []
        for t in tools:
            schema = t.args_schema if isinstance(t.args_schema, dict) else (t.args_schema.schema() if t.args_schema else {})
            params = schema.get("properties", {})
            param_str = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in params.items())
            tool_docs.append(f"- {t.name}({param_str}): {t.description}")
        question = f"What data sources are available for: {query}\n\nAvailable tools:\n" + "\n".join(tool_docs)
        if logger:
            logger.log("Planner", "Consulting data sources...")
        result = await CONSULTANTS["data"].consult(llm, tools, question)
        if logger:
            logger.log("Planner", f"Data consultation:\n{result[:500]}...")
        consultation_parts.append(f"## Available Data\n{result}")

    consultation_context = "\n\n".join(consultation_parts)
    if consultation_context:
        context_parts.append(f"## Research Results (embed these into step descriptions, do not re-research)\n{consultation_context}")

    feedback = state.get("planning_feedback")
    if feedback:
        context_parts.append(f"Previous plan was rejected. Feedback: {feedback}")

    context = "\n".join(context_parts) if context_parts else ""

    prompt = PROMPT.format(
        worker_docs=worker_docs,
        tool_docs=f"Available tools:\n{tool_docs}" if tool_docs else "",
        context=context,
    )

    if logger:
        logger.log("Planner", "Generating plan from LLM...")
    response = await llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=query)])
    if logger and response.content:
        logger.log("Planner", f"LLM response:\n{response.content[:800]}...")

    json_str = extract_json(response.content)
    if not json_str:
        return {"plan": None, "error": "No JSON found in planner response"}

    try:
        plan_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return {"plan": None, "error": f"JSON parse error: {e}"}

    result: Plan = {
        "id": str(uuid.uuid4()),
        "goal": plan_data["goal"],
        "status": "draft",
        "steps": [],
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
        })

    return {"plan": result, "planning_consultation_context": consultation_context}
