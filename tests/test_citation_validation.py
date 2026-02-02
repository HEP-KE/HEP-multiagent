import os
import tempfile

from hep_multiagent.features.citation_validation import (
    parse_quotes,
    validate_quote,
    get_source_text,
)


def test_parse_quotes_valid_json_list():
    result = parse_quotes('["quote one", "quote two"]')
    assert result == ["quote one", "quote two"]


def test_parse_quotes_empty_list():
    result = parse_quotes('[]')
    assert result == []


def test_parse_quotes_invalid_json():
    result = parse_quotes('not json')
    assert result == []


def test_parse_quotes_json_object_returns_empty():
    result = parse_quotes('{"key": "value"}')
    assert result == []


def test_parse_quotes_filters_non_strings():
    result = parse_quotes('["valid", 123, null, "also valid"]')
    assert result == ["valid", "also valid"]


def test_validate_quote_exact_match():
    assert validate_quote("hello world", "hello world")


def test_validate_quote_substring():
    assert validate_quote("world", "hello world")


def test_validate_quote_case_insensitive():
    assert validate_quote("HELLO", "hello world")


def test_validate_quote_ignores_whitespace():
    assert validate_quote("hello   world", "hello world")
    assert validate_quote("hello\nworld", "hello world")


def test_validate_quote_not_found():
    assert not validate_quote("foo bar", "hello world")


def test_get_source_text_from_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = os.path.join(tmpdir, "2301.00774.txt")
        with open(txt_path, "w") as f:
            f.write("This is the full paper text.")

        result = get_source_text("2301.00774", tmpdir, {})
        assert result == "This is the full paper text."


def test_get_source_text_fallback_to_metadata():
    with tempfile.TemporaryDirectory() as tmpdir:
        meta = {"title": "Paper Title", "abstract": "Paper abstract here."}
        result = get_source_text("9999.99999", tmpdir, meta)
        assert "Paper Title" in result
        assert "Paper abstract here" in result


def test_get_source_text_handles_slash_in_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = os.path.join(tmpdir, "astro-ph_0510346.txt")
        with open(txt_path, "w") as f:
            f.write("Old format paper text.")

        result = get_source_text("astro-ph/0510346", tmpdir, {})
        assert result == "Old format paper text."
