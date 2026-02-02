import json
import os


def validate_quote(quote: str, source_text: str) -> bool:
    if quote in source_text:
        return True
    return _normalize(quote) in _normalize(source_text)


def get_source_text(arxiv_id: str, output_dir: str, meta: dict) -> str:
    txt_path = os.path.join(output_dir, f"{arxiv_id.replace('/', '_')}.txt")
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"{meta.get('title', '')} {meta.get('abstract', '')}"


def parse_quotes(note: str) -> list:
    try:
        data = json.loads(note)
        return [q for q in data if isinstance(q, str)] if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}


def _normalize(text: str) -> str:
    for lig, chars in LIGATURES.items():
        text = text.replace(lig, chars)
    return " ".join(text.lower().split())
