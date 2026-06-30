from datetime import datetime
from types import SimpleNamespace

from hep_multiagent.features import arxiv_fetch
from hep_multiagent.features.arxiv_fetch import fetch_metadata, normalize_arxiv_id, search


class FakeClient:
    def results(self, search_request):
        ids = getattr(search_request, "id_list", None)
        if ids and ids[0] in {"9999.99999", "not-a-real-id"}:
            return iter([])
        return iter([
            SimpleNamespace(
                entry_id="https://arxiv.org/abs/2301.00774",
                title="Example Paper",
                authors=[SimpleNamespace(name="A. Author"), SimpleNamespace(name="B. Author")],
                published=datetime(2023, 1, 1),
                summary="A" * 150,
                pdf_url="https://arxiv.org/pdf/2301.00774",
            )
        ])


class FakeSearch:
    def __init__(self, query="", id_list=None, max_results=100):
        self.query = query
        self.id_list = id_list
        self.max_results = max_results


def patch_arxiv(monkeypatch):
    monkeypatch.setattr(
        arxiv_fetch,
        "_arxiv",
        lambda: SimpleNamespace(Client=FakeClient, Search=FakeSearch, HTTPError=RuntimeError),
    )


def test_fetch_valid_paper(monkeypatch):
    patch_arxiv(monkeypatch)
    meta = fetch_metadata("2301.00774")

    assert meta["arxiv_id"] == "2301.00774"
    assert meta["title"] == "Example Paper"
    assert meta["authors"] == "A. Author, B. Author"
    assert meta["year"] == "2023"
    assert len(meta["abstract"]) == 150


def test_fetch_invalid_paper(monkeypatch):
    patch_arxiv(monkeypatch)
    assert fetch_metadata("9999.99999") == {}


def test_fetch_malformed_id(monkeypatch):
    patch_arxiv(monkeypatch)
    assert fetch_metadata("not-a-real-id") == {}


def test_search_formats_results(monkeypatch):
    patch_arxiv(monkeypatch)
    results = search("dark matter", max_results=1)

    assert results == [{
        "arxiv_id": "2301.00774",
        "title": "Example Paper",
        "authors": "A. Author, B. Author",
        "year": "2023",
        "abstract": "A" * 150,
    }]


def test_normalize_strips_arxiv_prefix():
    assert normalize_arxiv_id("arXiv:2301.00774") == "2301.00774"
    assert normalize_arxiv_id("ARXIV:2301.00774") == "2301.00774"


def test_normalize_strips_url():
    assert normalize_arxiv_id("https://arxiv.org/abs/2301.00774") == "2301.00774"
    assert normalize_arxiv_id("http://arxiv.org/abs/2301.00774") == "2301.00774"
    assert normalize_arxiv_id("https://www.arxiv.org/abs/2301.00774") == "2301.00774"
    assert normalize_arxiv_id("arxiv.org/abs/2301.00774") == "2301.00774"


def test_normalize_strips_pdf_url():
    assert normalize_arxiv_id("https://arxiv.org/pdf/2301.00774") == "2301.00774"
    assert normalize_arxiv_id("https://arxiv.org/pdf/2301.00774.pdf") == "2301.00774"


def test_normalize_preserves_old_format():
    assert normalize_arxiv_id("astro-ph/0510346") == "astro-ph/0510346"
    assert normalize_arxiv_id("arXiv:astro-ph/0510346") == "astro-ph/0510346"
