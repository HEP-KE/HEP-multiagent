from langchain_core.tools import tool

from ..features import validators as validate
from ..features.agent_tools import save_json


PROMPT = """You are a scientific literature research specialist.

TOOLS: web_search, search_arxiv_abstracts, get_arxiv_metadata, download_arxiv_full_text, read_arxiv_chunk, cite, save_json

## When to Cite
cite() builds references.bib which appears in the final PDF report. You MUST decide:
- CITE if: paper findings will be discussed, compared, or referenced in the report
- SKIP if: task is purely metadata collection (counts, dates, lists) with no analysis

If skipping citations, state your reasoning: "Not citing because [task only requires metadata/no analysis needed]"

## Citation Workflow
1. Search: use search_arxiv_abstracts to find papers
2. Check: use get_arxiv_metadata for title/abstract
3. Quote: find verbatim text to cite (from abstract OR download full text)
4. Cite: call cite() with exact quotes - builds references.bib
5. If cite() fails (QUOTE FAILED): re-read source, copy exact text, retry

## Citation Format
- bib_path: output_dir + "/references.bib"
- note: JSON list of VERBATIM quotes: '["exact quote from paper"]'
- Quotes must match source exactly (character for character)
- You MAY cite using only abstract quotes (without downloading full text)

SEARCH STRATEGY:
- Use focused keyword queries (5-10 words)
- Example: "cool core cluster entropy threshold" not "what is a cool core cluster"

ERROR RECOVERY:
If cite() returns QUOTE FAILED:
1. The quote doesn't match the source text exactly
2. Re-read the source and copy the exact text
3. Retry cite() with corrected quote

Before each action, briefly state your reasoning.

REQUIRED: End your response with exactly one of:
- SUCCESS: <summary with specific values, thresholds, citations>
- FAILED: <reason why research could not be completed>"""


@tool
def web_search(query: str) -> str:
    """Search web for scientific info. NOT quotable - use only to find arxiv IDs.

    Args:
        query: Search terms, e.g. "galaxy cluster cool core entropy threshold"

    Returns:
        Search results as text. Use arxiv IDs found here with other tools.
    """
    # Input validation
    try:
        validate.non_empty(query, "query")
    except ValueError as e:
        return str(e)

    # Tool logic
    try:
        from langchain_community.tools import DuckDuckGoSearchRun
        return DuckDuckGoSearchRun().run(query)
    except Exception as e:
        return f"Search failed: {e}"


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
        return str(e)

    try:
        from ..features.arxiv_fetch import search
        results = search(query, max_results)
        if not results:
            return f"No papers found for: {query}"
        lines = []
        for p in results:
            lines.append(f"[{p['arxiv_id']}] {p['title']}\nAbstract: {p['abstract'][:300]}...\n")
        return "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


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
        return str(e)

    try:
        from ..features.arxiv_fetch import fetch_metadata
        meta = fetch_metadata(arxiv_id)
        if not meta:
            return f"Paper {arxiv_id} not found"
        return (
            f"arXiv ID: {meta['arxiv_id']}\n"
            f"Title: {meta['title']}\n"
            f"Authors: {meta['authors']}\n"
            f"Year: {meta['year']}\n"
            f"Abstract: {meta['abstract']}"
        )
    except Exception as e:
        return f"Metadata fetch failed: {e}"


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
        return str(e)

    try:
        from ..features.arxiv_fetch import download_full_text
        txt_path = download_full_text(arxiv_id, output_dir)
        return f"Downloaded: {txt_path}"
    except Exception as e:
        return f"Download failed: {e}"


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
        return str(e)

    try:
        from ..features.arxiv_fetch import read_chunk
        result = read_chunk(filepath, start, length)
        info = f"[chars {result['start']}-{result['end']} of {result['file_size']}]"
        if result['has_more']:
            info += f" (more available, next start={result['end']})"
        return f"{info}\n\n{result['text']}"
    except Exception as e:
        return f"Read failed: {e}"


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
        return str(e)

    try:
        from ..features.citation_builder import cite as do_cite
        result = do_cite(arxiv_id, note, bib_path)
        if not result["success"]:
            return result["error"]
        return f"Cited: {result['title']} (\\cite{{{result['key']}}})"
    except Exception as e:
        return f"Citation failed: {e}"


def get_research_tools():
    return [
        web_search,
        search_arxiv_abstracts,
        get_arxiv_metadata,
        download_arxiv_full_text,
        read_arxiv_chunk,
        cite,
        save_json,
    ]
