from typing import Any

from ..worker import run_consultation


PROMPT = """You are a data acquisition assistant.

Your job is to explain what data sources are available for a query.

Analyze the tool descriptions provided to understand what data can be fetched.

Provide a clear summary of:
- Available datasets and their contents
- Query parameters and filters
- How to fetch the data needed for the analysis"""


async def consult(llm: Any, tools: list, question: str, max_iterations: int = 10) -> str:
    return await run_consultation(llm, tools, PROMPT, question, max_iterations)
