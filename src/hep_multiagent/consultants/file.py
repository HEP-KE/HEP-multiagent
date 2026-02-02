from typing import Any, List

from ..worker import run_consultation


PROMPT = """You are a data exploration assistant.

Your job is to explore data files and report what's available.

Use inspect_datafile to see file structure and columns.

Provide a clear summary of:
- What columns/fields are available
- Data types and value ranges
- Key columns for the requested analysis"""


async def consult(llm: Any, tools: List, question: str, max_iterations: int = 10) -> str:
    return await run_consultation(llm, tools, PROMPT, question, max_iterations)
