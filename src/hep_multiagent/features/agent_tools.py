import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from langchain_core.tools import tool

from . import validators as validate


@tool
def save_json(filepath: str, data) -> str:
    """Save data as JSON file for other workers to read.

    Args:
        filepath: Output path ending in .json, e.g. output_dir + "/results.json"
        data: Dictionary, list, or JSON string to save

    Returns:
        Success message with filepath, or error if save failed.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            return f"Invalid JSON string: {e}"

    try:
        validate.non_empty(filepath, "filepath")
        validate.extension(filepath, [".json"])
        validate.json_serializable(data)
    except ValueError as e:
        return str(e)

    # Tool logic
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        return f"Failed to save: {e}"

    # Output validation
    try:
        validate.file_written(filepath)
    except (ValueError, OSError) as e:
        return str(e)

    return f"Saved: {filepath}"


@tool
def list_data_keys(filepath: str) -> str:
    """List keys in a JSON file to understand its structure.

    Args:
        filepath: Path to .json file

    Returns:
        List of top-level keys if dict, or item count if list.
    """
    try:
        validate.file_exists(filepath)
        validate.extension(filepath, [".json"])
    except ValueError as e:
        return str(e)

    try:
        with open(filepath) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return f"Keys: {list(data.keys())}"
        return f"List with {len(data)} items" if isinstance(data, list) else str(type(data))
    except Exception as e:
        return f"Failed to read file: {e}"


@tool
def load_json(filepath: str, key: str = None) -> str:
    """Load JSON file contents. Use to read data saved by other workers.

    Args:
        filepath: Path to .json file
        key: Optional key to extract specific value from dict

    Returns:
        JSON content as string, or specific value if key provided.
    """
    try:
        validate.file_exists(filepath)
        validate.extension(filepath, [".json"])
    except ValueError as e:
        return str(e)

    try:
        with open(filepath) as f:
            data = json.load(f)
        if key:
            if not isinstance(data, dict):
                return f"Cannot extract key from non-dict: {type(data)}"
            if key not in data:
                return f"Key '{key}' not found. Available: {list(data.keys())}"
            data = data[key]
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Failed to load file: {e}"


def _load_array(filepath: str):
    if filepath.endswith('.npy'):
        return np.load(filepath, allow_pickle=True)
    if filepath.endswith('.json'):
        with open(filepath) as f:
            data = json.load(f)
        return np.array(data) if isinstance(data, list) else data
    raise ValueError(f"Unsupported format: {filepath}")


def _save_plot(output_path: str) -> str:
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    return f"Saved: {output_path}"


@tool
def create_bar_chart(data_file: str, output_path: str, title: str = "Bar Chart", xlabel: str = "Category", ylabel: str = "Count") -> str:
    """Create bar chart from JSON data.

    Args:
        data_file: Path to .json with {key: value} pairs or {labels: [], values: []}
        output_path: Output image path, e.g. output_dir + "/chart.png"
        title: Chart title
        xlabel: X-axis label
        ylabel: Y-axis label

    Returns:
        Path to saved image file.
    """
    try:
        validate.file_exists(data_file)
        validate.extension(data_file, [".json"])
        validate.non_empty(output_path, "output_path")
        validate.extension(output_path, [".png", ".pdf", ".jpg", ".jpeg"])
        validate.non_empty(title, "title")
        validate.non_empty(xlabel, "xlabel")
        validate.non_empty(ylabel, "ylabel")
    except ValueError as e:
        return str(e)

    try:
        with open(data_file) as f:
            data = json.load(f)
        if "year_counts" in data:
            labels, values = list(data["year_counts"].keys()), list(data["year_counts"].values())
        elif "labels" in data and "values" in data:
            labels, values = data["labels"], data["values"]
        else:
            # Filter to only numeric values (skip nested dicts, lists, strings)
            labels, values = [], []
            for k, v in data.items():
                if isinstance(v, (int, float)):
                    labels.append(k)
                    values.append(v)
            if not labels:
                return f"No numeric values found. Keys: {list(data.keys())}. Use {{labels: [], values: []}} format."

        plt.figure(figsize=(10, 6))
        plt.bar(labels, values, edgecolor='black', alpha=0.7)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.title(title)
        plt.xticks(rotation=45, ha='right')
        return _save_plot(output_path)
    except Exception as e:
        return f"Failed to create chart: {e}"


@tool
def create_histogram(data_file: str, output_path: str, key: str = None, title: str = "Histogram", bins: int = 30, log_y: bool = False) -> str:
    """Create histogram from array data.

    Args:
        data_file: Path to .npy or .json file containing array
        output_path: Output image path, e.g. output_dir + "/hist.png"
        key: If JSON is dict, which key contains the array
        title: Chart title
        bins: Number of histogram bins (default 30)
        log_y: Use log scale on y-axis

    Returns:
        Path to saved image file.
    """
    try:
        validate.file_exists(data_file)
        validate.extension(data_file, [".npy", ".json"])
        validate.non_empty(output_path, "output_path")
        validate.extension(output_path, [".png", ".pdf", ".jpg", ".jpeg"])
        validate.non_empty(title, "title")
        validate.positive_int(bins, "bins")
    except ValueError as e:
        return str(e)

    try:
        data = _load_array(data_file)
        if isinstance(data, dict):
            if not key:
                return f"JSON is dict with keys {list(data.keys())}. Specify key param."
            data = np.array(data[key])

        plt.figure(figsize=(10, 6))
        plt.hist(data, bins=bins, edgecolor='black', alpha=0.7)
        plt.title(title)
        if log_y:
            plt.yscale('log')
        return _save_plot(output_path)
    except Exception as e:
        return f"Failed to create histogram: {e}"


@tool
def create_scatter_plot(x_file: str, y_file: str, output_path: str, title: str = "Scatter Plot", log_x: bool = False, log_y: bool = False) -> str:
    """Create scatter plot from two arrays of equal length.

    Args:
        x_file: Path to .npy or .json file for x-axis values
        y_file: Path to .npy or .json file for y-axis values
        output_path: Output image path, e.g. output_dir + "/scatter.png"
        title: Chart title
        log_x: Use log scale on x-axis
        log_y: Use log scale on y-axis

    Returns:
        Path to saved image file.
    """
    try:
        validate.file_exists(x_file)
        validate.extension(x_file, [".npy", ".json"])
        validate.file_exists(y_file)
        validate.extension(y_file, [".npy", ".json"])
        validate.non_empty(output_path, "output_path")
        validate.extension(output_path, [".png", ".pdf", ".jpg", ".jpeg"])
        validate.non_empty(title, "title")
    except ValueError as e:
        return str(e)

    try:
        x, y = _load_array(x_file), _load_array(y_file)
        validate.arrays_same_length(x, y)

        plt.figure(figsize=(10, 8))
        plt.scatter(x, y, alpha=0.6, s=20)
        plt.title(title)
        if log_x:
            plt.xscale('log')
        if log_y:
            plt.yscale('log')
        return _save_plot(output_path)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Failed to create scatter plot: {e}"


@tool
def create_line_plot(x_file: str, y_file: str, output_path: str, title: str = "Line Plot") -> str:
    """Create line plot from two arrays of equal length.

    Args:
        x_file: Path to .npy or .json file for x-axis values
        y_file: Path to .npy or .json file for y-axis values
        output_path: Output image path, e.g. output_dir + "/line.png"
        title: Chart title

    Returns:
        Path to saved image file.
    """
    try:
        validate.file_exists(x_file)
        validate.extension(x_file, [".npy", ".json"])
        validate.file_exists(y_file)
        validate.extension(y_file, [".npy", ".json"])
        validate.non_empty(output_path, "output_path")
        validate.extension(output_path, [".png", ".pdf", ".jpg", ".jpeg"])
        validate.non_empty(title, "title")
    except ValueError as e:
        return str(e)

    try:
        x, y = _load_array(x_file), _load_array(y_file)
        validate.arrays_same_length(x, y)

        plt.figure(figsize=(10, 6))
        plt.plot(x, y, marker='o', linewidth=2)
        plt.title(title)
        plt.grid(True, alpha=0.3)
        return _save_plot(output_path)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Failed to create line plot: {e}"
