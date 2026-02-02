import json
import os
import re


def non_empty(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} cannot be empty")


def arxiv_id(value: str) -> None:
    non_empty(value, "arxiv_id")
    patterns = [r"^\d{4}\.\d{4,5}(v\d+)?$", r"^[a-z-]+/\d{7}$"]
    if not any(re.match(p, value) for p in patterns):
        raise ValueError(f"Invalid arxiv_id format: {value}")


def file_exists(filepath: str) -> None:
    non_empty(filepath, "filepath")
    if not os.path.exists(filepath):
        raise ValueError(f"File not found: {filepath}")


def dir_exists(dirpath: str) -> None:
    non_empty(dirpath, "directory")
    if not os.path.isdir(dirpath):
        raise ValueError(f"Directory not found: {dirpath}")


def extension(filepath: str, allowed: list) -> None:
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in allowed:
        raise ValueError(f"File must have extension {allowed}, got: {ext}")


def json_list(value: str, name: str = "value") -> None:
    non_empty(value, name)
    try:
        data = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"{name} is not valid JSON: {e}")
    if not isinstance(data, list):
        raise ValueError(f"{name} must be a JSON list, got {type(data).__name__}")


def json_serializable(data, name: str = "data") -> None:
    try:
        json.dumps(data)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} is not JSON-serializable: {e}")


def positive_int(value: int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got: {value}")


def non_negative_int(value: int, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} cannot be negative, got: {value}")


def int_range(value: int, min_val: int, max_val: int, name: str) -> None:
    if not min_val <= value <= max_val:
        raise ValueError(f"{name} must be between {min_val} and {max_val}, got: {value}")


def file_written(filepath: str, min_size: int = 1) -> None:
    size = os.path.getsize(filepath)
    if size < min_size:
        raise ValueError(f"File is empty or too small: {filepath}")


def arrays_same_length(x, y) -> None:
    if len(x) != len(y):
        raise ValueError(f"Array length mismatch: x has {len(x)}, y has {len(y)}")


def text_not_empty(text: str, min_chars: int = 100) -> None:
    if len(text.strip()) < min_chars:
        raise ValueError(f"Text too short: got {len(text.strip())} chars, need {min_chars}")
