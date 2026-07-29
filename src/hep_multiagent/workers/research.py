from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool

from ..features import validators as validate
from ..features.arxiv_fetch import download_full_text, fetch_metadata, read_chunk, search
from ..features.citation_builder import cite as build_citation


PROMPT = """You are a research worker. Your job: search arxiv, get paper metadata, cite papers.

## CRITICAL: Do Exactly What's Asked
- Do ONLY what the task description says. Nothing more.
- If task says "find 5 papers", find 5 papers. Don't analyze them unless asked.
- If task says "cite these papers", cite them. Don't summarize unless asked.
- Simple task = simple solution.

## Your Role (stay in scope)
- Search arxiv for papers
- Get paper metadata (title, authors, abstract, year)
- Download and read paper text when needed
- Cite papers to build references.bib
Do NOT: compute statistics (compute worker), create plots (viz worker), fetch non-arxiv data (data worker)

## Citation Workflow
1. get_arxiv_metadata to get abstract
2. cite(arxiv_id, '["verbatim quote from abstract"]', output_dir+"/references.bib")
3. Only download full text if you need quotes not in abstract

## When to Cite
- CITE if paper content will appear in the final report
- SKIP if task only needs metadata (counts, lists, dates)

## Search Strategy
- Focused keyword queries: "galaxy cluster cool core entropy"
- NOT questions: "what is a cool core cluster"

## Report Issues
Call log_issue(component, problem, suggestion) when you:
- Encounter a tool failure or unexpected result
- Notice an opportunity for a new tool that would help

REQUIRED: the completion tool must include ALL outputs produced (paper IDs, citation keys, file paths) so downstream workers can use them."""


@tool
def web_search(query: str) -> str:
    """Search web for scientific info. NOT quotable - use only to find arxiv IDs.

    Args:
        query: Search terms, e.g. "galaxy cluster cool core entropy threshold"

    Returns:
        Search results as text. Use arxiv IDs found here with other tools.
    """
    try:
        validate.non_empty(query, "query")
    except ValueError as e:
        return f"Error: {e}"

    try:
        return DuckDuckGoSearchRun().run(query)
    except Exception as e:
        return f"Error: Search failed: {e}"


@tool
def search_arxiv_abstracts(query: str, max_results: int = 5) -> str:
    """Search arxiv for papers. Returns titles and abstracts only, NOT full text.

    Args:
        query: Search terms, e.g. "stellar mass function SDSS"
        max_results: Number of papers to return (1-50, default 5)

    Returns:
        List of papers with arxiv_id, title, and truncated abstract.
    """
    try:
        validate.non_empty(query, "query")
        validate.int_range(max_results, 1, 50, "max_results")
    except ValueError as e:
        return f"Error: {e}"

    try:
        results = search(query, max_results)
        if not results:
            return f"No papers found for: {query}"
        lines = []
        for p in results:
            lines.append(f"[{p['arxiv_id']}] {p['title']}\nAbstract: {p['abstract'][:300]}...\n")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: Search failed: {e}"


@tool
def get_arxiv_metadata(arxiv_id: str) -> str:
    """Get paper metadata without downloading. Use for quick checks.

    Args:
        arxiv_id: Paper ID, e.g. "2301.00774" or "astro-ph/0510346"

    Returns:
        Title, authors, year, and full abstract text.
    """
    try:
        validate.arxiv_id(arxiv_id)
    except ValueError as e:
        return f"Error: {e}"

    try:
        meta = fetch_metadata(arxiv_id)
        if not meta:
            return f"Error: Paper {arxiv_id} not found"
        return (
            f"arXiv ID: {meta['arxiv_id']}\n"
            f"Title: {meta['title']}\n"
            f"Authors: {meta['authors']}\n"
            f"Year: {meta['year']}\n"
            f"Abstract: {meta['abstract']}"
        )
    except Exception as e:
        return f"Error: Metadata fetch failed: {e}"


@tool
def download_arxiv_full_text(arxiv_id: str, output_dir: str) -> str:
    """Download paper PDF and extract full text. Use for finding quotable text.

    Args:
        arxiv_id: Paper ID, e.g. "2301.00774" or "astro-ph/0510346"
        output_dir: Directory to save files

    Returns:
        Path to extracted .txt file. Use read_arxiv_chunk to read contents.
    """
    try:
        validate.arxiv_id(arxiv_id)
        validate.dir_exists(output_dir)
    except ValueError as e:
        return f"Error: {e}"

    try:
        txt_path = download_full_text(arxiv_id, output_dir)
        return f"Downloaded: {txt_path}"
    except Exception as e:
        return f"Error: Download failed: {e}"


@tool
def read_arxiv_chunk(filepath: str, start: int = 0, length: int = 10000) -> str:
    """Read a chunk of downloaded paper text. Use to find exact quotes for cite().

    Args:
        filepath: Path to .txt file from download_arxiv_full_text
        start: Character position to start reading (default 0)
        length: Number of characters to read (default 10000)

    Returns:
        Text chunk with position info. If has_more=true, call again with next start.
    """
    try:
        validate.file_exists(filepath)
        validate.non_negative_int(start, "start")
        validate.positive_int(length, "length")
    except ValueError as e:
        return f"Error: {e}"

    try:
        result = read_chunk(filepath, start, length)
        info = f"[chars {result['start']}-{result['end']} of {result['file_size']}]"
        if result['has_more']:
            info += f" (more available, next start={result['end']})"
        return f"{info}\n\n{result['text']}"
    except Exception as e:
        return f"Error: Read failed: {e}"


@tool
def cite(arxiv_id: str, note: str, bib_path: str) -> str:
    """Add paper to .bib file with validated verbatim quotes.

    Args:
        arxiv_id: Paper ID, e.g. "2301.00774" or "astro-ph/0510346"
        note: JSON list of exact quotes, e.g. '["entropy threshold of 30 keV cm^2"]'
        bib_path: Path to .bib file, use output_dir + "/references.bib"

    Returns:
        Success with citation key, or QUOTE FAILED if quote not found in source.
        If failed, re-read source text, copy exact quote, and retry.
    """
    try:
        validate.arxiv_id(arxiv_id)
        validate.json_list(note, "note")
        validate.non_empty(bib_path, "bib_path")
        validate.extension(bib_path, [".bib"])
    except ValueError as e:
        return f"Error: {e}"

    try:
        result = build_citation(arxiv_id, note, bib_path)
        if not result["success"]:
            return f"Error: {result['error']}"
        return f"Cited: {result['title']} (\\cite{{{result['key']}}})"
    except Exception as e:
        return f"Error: Citation failed: {e}"


def get_research_tools(output_dir=None, available_tools=None):
    return [
        web_search,
        search_arxiv_abstracts,
        get_arxiv_metadata,
        download_arxiv_full_text,
        read_arxiv_chunk,
        cite,
    ]
