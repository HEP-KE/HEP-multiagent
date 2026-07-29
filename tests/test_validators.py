import pytest

from hep_multiagent.features import validators as validate


def test_arxiv_id_accepts_supported_formats():
    validate.arxiv_id("2301.00774")
    validate.arxiv_id("2301.00774v2")
    validate.arxiv_id("astro-ph/0510346")


def test_arxiv_id_rejects_bad_input():
    with pytest.raises(ValueError, match="Invalid arxiv_id format"):
        validate.arxiv_id("not-valid")


def test_json_list_rejects_non_list_json():
    with pytest.raises(ValueError, match="must be a JSON list"):
        validate.json_list('{"key": "value"}', "note")


def test_int_range_rejects_out_of_bounds_values():
    with pytest.raises(ValueError, match="must be between"):
        validate.int_range(0, 1, 10, "max_results")
