import json
import os
import re

from .arxiv_fetch import fetch_metadata
from .citation_validation import parse_quotes, get_source_text, validate_quote


def _merge_quotes(bib_path: str, arxiv_id: str, new_quotes: list) -> tuple[str, str]:
    if not os.path.exists(bib_path):
        return "", json.dumps(new_quotes)
    with open(bib_path) as f:
        content = f.read()
    pattern = rf"@article\{{[^,]+,.*?eprint\s*=\s*\{{{re.escape(arxiv_id)}\}}.*?\n\}}\n*"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return content, json.dumps(new_quotes)
    old_note = re.search(r"note\s*=\s*\{(.+?)\}", match.group(0), re.DOTALL)
    old_quotes = parse_quotes(old_note.group(1)) if old_note else []
    merged = old_quotes + [q for q in new_quotes if q not in old_quotes]
    return content.replace(match.group(0), ""), json.dumps(merged)


def cite(arxiv_id: str, note: str, bib_path: str) -> dict:
    output_dir = os.path.dirname(bib_path)

    meta = fetch_metadata(arxiv_id)
    if not meta:
        return {"success": False, "error": f"METADATA FAILED: arxiv_id {arxiv_id} not found"}

    new_quotes = parse_quotes(note)
    if not new_quotes:
        return {"success": False, "error": "QUOTE FAILED: note must be JSON list of quotes"}

    source_text = get_source_text(arxiv_id, output_dir, meta)
    if not source_text:
        return {"success": False, "error": f"QUOTE FAILED: No source text for {arxiv_id}"}

    for q in new_quotes:
        if not validate_quote(q, source_text):
            return {"success": False, "error": f"QUOTE FAILED: \"{q[:80]}\" not found in source"}

    content, merged_note = _merge_quotes(bib_path, arxiv_id, new_quotes)
    key = f"arxiv{arxiv_id.replace('.', '').replace('/', '').replace('-', '')}"
    entry = (
        f"@article{{{key},\n"
        f"  title = {{{meta['title']}}},\n"
        f"  author = {{{meta['authors'].replace(', ', ' and ')}}},\n"
        f"  year = {{{meta['year']}}},\n"
        f"  eprint = {{{arxiv_id}}},\n"
        f"  note = {{{merged_note}}}\n"
        f"}}\n\n"
    )

    os.makedirs(output_dir, exist_ok=True)
    with open(bib_path, "w") as f:
        f.write((content.strip() + "\n\n" + entry) if content.strip() else entry)

    return {"success": True, "key": key, "title": meta["title"]}


class BibTeXManager:
    def export(self, output_dir: str) -> str:
        bib_path = os.path.join(output_dir, "references.bib")
        return bib_path
