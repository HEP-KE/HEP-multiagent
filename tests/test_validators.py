import os
import tempfile
import pytest

from hep_multiagent.features import validators as validate


def test_non_empty_valid():
    validate.non_empty("hello", "test")  # should not raise


def test_non_empty_raises_on_empty():
    with pytest.raises(ValueError, match="cannot be empty"):
        validate.non_empty("", "field")


def test_non_empty_raises_on_whitespace():
    with pytest.raises(ValueError, match="cannot be empty"):
        validate.non_empty("   ", "field")


def test_arxiv_id_new_format():
    validate.arxiv_id("2301.00774")
    validate.arxiv_id("2301.00774v2")


def test_arxiv_id_old_format():
    validate.arxiv_id("astro-ph/0510346")
    validate.arxiv_id("hep-th/9802150")


def test_arxiv_id_invalid():
    with pytest.raises(ValueError, match="Invalid arxiv_id format"):
        validate.arxiv_id("not-valid")


def test_arxiv_id_empty():
    with pytest.raises(ValueError, match="cannot be empty"):
        validate.arxiv_id("")


def test_file_exists_valid():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"test")
        path = f.name
    try:
        validate.file_exists(path)
    finally:
        os.unlink(path)


def test_file_exists_missing():
    with pytest.raises(ValueError, match="File not found"):
        validate.file_exists("/nonexistent/path.txt")


def test_dir_exists_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        validate.dir_exists(tmpdir)


def test_dir_exists_missing():
    with pytest.raises(ValueError, match="Directory not found"):
        validate.dir_exists("/nonexistent/dir")


def test_extension_valid():
    validate.extension("file.json", [".json"])
    validate.extension("file.PNG", [".png", ".jpg"])


def test_extension_invalid():
    with pytest.raises(ValueError, match="must have extension"):
        validate.extension("file.txt", [".json"])


def test_json_list_valid():
    validate.json_list('["a", "b"]', "test")
    validate.json_list('[]', "test")


def test_json_list_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        validate.json_list("not json", "test")


def test_json_list_not_list():
    with pytest.raises(ValueError, match="must be a JSON list"):
        validate.json_list('{"key": "value"}', "test")


def test_json_serializable_valid():
    data = {"key": "value", "num": 123}
    validate.json_serializable(data)


def test_json_serializable_invalid():
    with pytest.raises(ValueError, match="not JSON-serializable"):
        validate.json_serializable({"func": lambda x: x})


def test_positive_int_valid():
    validate.positive_int(5, "count")


def test_positive_int_zero():
    with pytest.raises(ValueError, match="must be positive"):
        validate.positive_int(0, "count")


def test_positive_int_negative():
    with pytest.raises(ValueError, match="must be positive"):
        validate.positive_int(-1, "count")


def test_non_negative_int_valid():
    validate.non_negative_int(0, "start")
    validate.non_negative_int(5, "start")


def test_non_negative_int_invalid():
    with pytest.raises(ValueError, match="cannot be negative"):
        validate.non_negative_int(-1, "start")


def test_int_range_valid():
    validate.int_range(5, 1, 10, "value")
    validate.int_range(1, 1, 10, "value")
    validate.int_range(10, 1, 10, "value")


def test_int_range_invalid():
    with pytest.raises(ValueError, match="must be between"):
        validate.int_range(0, 1, 10, "value")
    with pytest.raises(ValueError, match="must be between"):
        validate.int_range(11, 1, 10, "value")


def test_file_written_valid():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"test content")
        path = f.name
    try:
        validate.file_written(path)
    finally:
        os.unlink(path)


def test_file_written_missing():
    with pytest.raises(OSError):
        validate.file_written("/nonexistent/file.txt")


def test_file_written_empty():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    try:
        with pytest.raises(ValueError, match="empty or too small"):
            validate.file_written(path)
    finally:
        os.unlink(path)


def test_arrays_same_length_valid():
    validate.arrays_same_length([1, 2, 3], [4, 5, 6])


def test_arrays_same_length_mismatch():
    with pytest.raises(ValueError, match="length mismatch"):
        validate.arrays_same_length([1, 2], [1, 2, 3])


def test_text_not_empty_valid():
    validate.text_not_empty("x" * 100, min_chars=100)


def test_text_not_empty_too_short():
    with pytest.raises(ValueError, match="too short"):
        validate.text_not_empty("short", min_chars=100)
