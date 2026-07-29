import logging
import os
import re

import arxiv
from pypdf import PdfReader
import requests

from . import validators as validate


def normalize_arxiv_id(arxiv_id: str) -> str:
    s = arxiv_id.strip()
    s = re.sub(r'^https?://(www\.)?arxiv\.org/(abs|pdf)/', '', s)
    s = re.sub(r'^arxiv\.org/(abs|pdf)/', '', s)
    s = re.sub(r'^arXiv:', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\.pdf$', '', s)
    return s


def fetch_metadata(arxiv_id: str) -> dict | None:
    clean_id = normalize_arxiv_id(arxiv_id)
    try:
        paper = next(arxiv.Client().results(arxiv.Search(id_list=[clean_id])), None)
    except arxiv.HTTPError:
        return None
    if not paper:
        return None
    return {
        "arxiv_id": clean_id,
        "title": paper.title,
        "authors": ", ".join(a.name for a in paper.authors),
        "year": str(paper.published.year),
        "abstract": paper.summary,
        "pdf_url": paper.pdf_url,
    }


def search(query: str, max_results: int = 5) -> list:
    client = arxiv.Client()
    results = client.results(arxiv.Search(query=query, max_results=max_results))
    papers = []
    for paper in results:
        papers.append({
            "arxiv_id": paper.entry_id.split("/")[-1],
            "title": paper.title,
            "authors": ", ".join(a.name for a in paper.authors),
            "year": str(paper.published.year),
            "abstract": paper.summary,
        })
    return papers


def download_pdf(arxiv_id: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)

    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    filepath = os.path.join(output_dir, f"{arxiv_id.replace('/', '_')}.pdf")

    resp = requests.get(url)
    resp.raise_for_status()

    with open(filepath, "wb") as f:
        f.write(resp.content)

    return filepath


def extract_text_from_pdf(pdf_path: str) -> str:
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        pages.append(f"--- Page {i} ---\n{page.extract_text()}")
    return "\n\n".join(pages)


def download_full_text(arxiv_id: str, output_dir: str) -> str:
    meta = fetch_metadata(arxiv_id)
    if not meta:
        raise ValueError(f"Paper {arxiv_id} not found")

    pdf_path = download_pdf(arxiv_id, output_dir)
    text = extract_text_from_pdf(pdf_path)
    validate.text_not_empty(text, min_chars=100)

    txt_path = os.path.join(output_dir, f"{arxiv_id.replace('/', '_')}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Title: {meta['title']}\n")
        f.write(f"Authors: {meta['authors']}\n")
        f.write(f"Year: {meta['year']}\n")
        f.write(f"arXiv ID: {arxiv_id}\n\n")
        f.write("=" * 60 + "\n\n")
        f.write(text)

    return txt_path


def read_chunk(filepath: str, start: int = 0, length: int = 10000) -> dict:
    with open(filepath, "r", encoding="utf-8") as f:
        f.seek(0, 2)
        file_size = f.tell()
        f.seek(start)
        text = f.read(length)

    return {
        "text": text,
        "start": start,
        "end": start + len(text),
        "file_size": file_size,
        "has_more": start + len(text) < file_size,
    }
