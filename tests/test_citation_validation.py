import os
import tempfile

from hep_multiagent.features.citation_validation import (
    parse_quotes,
    validate_quote,
    get_source_text,
)


def test_parse_quotes_filters_valid_strings():
    result = parse_quotes('["valid", 123, null, "also valid"]')
    assert result == ["valid", "also valid"]


def test_parse_quotes_rejects_invalid_json_shape():
    assert parse_quotes("not json") == []
    assert parse_quotes('{"key": "value"}') == []


def test_validate_quote_matches_normalized_source_text():
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


def test_get_source_text_handles_slash_in_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = os.path.join(tmpdir, "astro-ph_0510346.txt")
        with open(txt_path, "w") as f:
            f.write("Old format paper text.")

        result = get_source_text("astro-ph/0510346", tmpdir, {})
        assert result == "Old format paper text."
