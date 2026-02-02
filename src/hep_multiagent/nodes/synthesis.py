import os
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ..state import AgentState, Plan
from ..features.report_generator import ReportData, ReportSection


PROMPT = r"""Document execution of an agentic LLM system. Write LaTeX body content (no \documentclass or preamble).

## Original Query
{query}

## Execution Summary
{execution_summary}

## Citations
{citations}

## Report Structure

\section{{Answer}}
\textbf{{\textcolor{{blue}}{{Direct answer to the user's query here.}}}}
State the answer immediately. If the system could not answer, state that directly.

\section{{Execution Log}}
For each step document which worker/node executed it, which tools or MCP servers were invoked.
Include the LLM's observations, adjustments, workarounds, retries at each step.
Note failures, errors, and gaps \textbf{{inline where they occurred}} - be specific, not verbose.
Write: "The data worker queried...", "The compute worker encountered error X when..."
Do NOT invent explanations for failures.

\section{{Results}}
Quantitative values such as specific numbers, thresholds, and units  in \textbf{{\textcolor{{blue}}{{bold red}}}} with units.
Attribute each result to the component that produced it.
Integrate figures with academic captions: \begin{{figure}}[h]\centering\includegraphics{{...}}\caption{{Descriptive caption.}}\end{{figure}}
Do NOT include raw data dumps.
Include helpful tables. For wide tables, wrap with: \fitbox{{\begin{{tabular}}{{...}}...\end{{tabular}}}}

\section{{Discussion}}
Key takeaways - be opinionated based on evidence.
Limitations: what the system could not do or verify.
Gaps: what information is missing or uncertain.
Failed steps: list specific failures and their impact on conclusions.

## Citation Guidelines
CRITICAL: Cite papers using their arXiv ID in brackets exactly as shown in the Citations section.
- CORRECT: "Dark matter detection methods vary [arXiv:1211.7222]"
- WRONG: [?] or [1] or \cite{{}} or (Author et al.)
- Only cite papers listed above - do not invent citations

## Formatting Rules
- No flowery language - direct and factual
- Quantitative values: \textbf{{\textcolor{{blue}}{{value with units}}}}
- Never invent explanations
- No raw tool outputs
"""


async def synthesize(state: AgentState, llm: Any, report_writer, references, logger=None) -> dict:
    plan = state.get("plan")
    if not plan:
        return {"final_report": "No plan created.", "next_action": "end"}

    query = ""
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            query = msg.content
            break

    output_dir = state.get("output_dir", ".")
    references.load(output_dir)

    cite_keys = _read_bib_keys(output_dir)
    execution_summary = _build_execution_summary(plan)
    prompt = PROMPT.format(execution_summary=execution_summary, query=query, citations=cite_keys)

    if logger:
        logger.log("Synthesis", "Calling LLM for report generation...")

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content
    except Exception as e:
        if logger:
            logger.log("Synthesis", f"LLM error: {e}, using fallback")
        content = _fallback_report(plan, query)

    if logger:
        logger.log("Synthesis", "LLM response received, generating PDF...")

    sections = [ReportSection(title="Report", content=content)]
    figures = _collect_figures(plan)
    data = ReportData(
        title=plan["goal"],
        query=query,
        sections=sections,
        figures=figures,
    )

    references.export(output_dir)
    report_writer.generate(data, output_dir, logger)

    if logger:
        logger.log("Synthesis", "Report complete")

    return {"final_report": content, "next_action": "end", "messages": [AIMessage(content=content)]}


def _read_bib_keys(output_dir: str) -> str:
    bib_path = os.path.join(output_dir, "references.bib")
    if not os.path.exists(bib_path):
        return "No papers available to cite."
    content = open(bib_path).read()
    entries = []
    for match in re.finditer(r"@\w+\{(\w+),(.+?)\n\}", content, re.DOTALL):
        body = match.group(2)
        eprint = re.search(r"eprint\s*=\s*\{(.+?)\}", body, re.DOTALL)
        title = re.search(r"title\s*=\s*\{(.+?)\}", body, re.DOTALL)
        author = re.search(r"author\s*=\s*\{(.+?)\}", body, re.DOTALL)
        note = re.search(r"note\s*=\s*\{(.+?)\}", body, re.DOTALL)
        arxiv_id = eprint.group(1).strip() if eprint else "unknown"
        entry = f"- [arXiv:{arxiv_id}]: {title.group(1).strip() if title else 'Unknown'}"
        if author:
            entry += f" by {author.group(1).strip()}"
        if note:
            entry += f"\n  Quotes: {note.group(1).strip()}"
        entries.append(entry)
    if not entries:
        return "No papers available to cite."
    return "USE ONLY THESE CITATIONS (do not invent others):\n" + "\n".join(entries)


def _build_execution_summary(plan: Plan) -> str:
    lines = [f"Goal: {plan['goal']}\n"]
    for step in plan.get("steps", []):
        status = "✓" if step["status"] == "completed" else "✗"
        lines.append(f"### {status} {step['name']} [{step['worker_type']}]")
        lines.append(f"Task: {step['description']}")
        if step.get("solution"):
            lines.append(f"Result: {step['solution'][:500]}")
        if step.get("error"):
            lines.append(f"ERROR: {step['error']}")
        if step.get("artifacts"):
            lines.append(f"Files: {', '.join(step['artifacts'])}")
        lines.append("")
    return "\n".join(lines)


def _fallback_report(plan: Plan, query: str) -> str:
    lines = [f"# {plan['goal']}", "", "## Query", query, "", "## Steps"]
    for step in plan["steps"]:
        status = "✓" if step["status"] == "completed" else "✗"
        lines.append(f"\n### {status} {step['name']}")
        if step.get("solution"):
            lines.append(step["solution"])
        if step.get("error"):
            lines.append(f"**Error:** {step['error']}")
    return "\n".join(lines)


def _collect_figures(plan: Plan) -> list[str]:
    exts = {".png", ".pdf", ".jpg", ".jpeg"}
    return [a for s in plan.get("steps", []) for a in s.get("artifacts", []) if os.path.splitext(a)[1].lower() in exts]
