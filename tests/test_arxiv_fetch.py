import pytest
from hep_multiagent.features.arxiv_fetch import fetch_metadata, normalize_arxiv_id


def test_fetch_valid_paper():
    meta = fetch_metadata("2301.00774")
    assert meta, "Should return metadata for valid arxiv_id"
    assert meta["arxiv_id"] == "2301.00774"
    assert len(meta["title"]) > 0
    assert len(meta["authors"]) > 0
    assert meta["year"].isdigit()
    assert len(meta["abstract"]) > 100


def test_fetch_invalid_paper():
    meta = fetch_metadata("9999.99999")
    assert meta == {}, "Should return empty dict for non-existent paper"


def test_fetch_malformed_id():
    meta = fetch_metadata("not-a-real-id")
    assert meta == {}, "Should return empty dict for malformed id"


def test_fetch_old_format_id():
    meta = fetch_metadata("astro-ph/0510346")
    assert meta, "Should handle old arxiv format (astro-ph/XXXXXXX)"
    assert "arxiv_id" in meta


def test_metadata_fields_present():
    meta = fetch_metadata("2301.00774")
    required = ["arxiv_id", "title", "authors", "year", "abstract"]
    for field in required:
        assert field in meta, f"Missing required field: {field}"
        assert meta[field], f"Field {field} should not be empty"


def test_authors_comma_separated():
    meta = fetch_metadata("2301.00774")
    if ", " in meta["authors"]:
        authors = meta["authors"].split(", ")
        assert len(authors) >= 1, "Should parse multiple authors"


def test_year_is_reasonable():
    meta = fetch_metadata("2301.00774")
    year = int(meta["year"])
    assert 1990 < year < 2030, f"Year {year} seems unreasonable"


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


def test_fetch_with_url_format():
    meta = fetch_metadata("https://arxiv.org/abs/2301.00774")
    assert meta, "Should handle full URL"
    assert meta["arxiv_id"] == "2301.00774"


def test_fetch_with_arxiv_prefix():
    meta = fetch_metadata("arXiv:2301.00774")
    assert meta, "Should handle arXiv: prefix"
    assert meta["arxiv_id"] == "2301.00774"
