from hep_multiagent.features.run_local_tools import (
    create_run_local_tool,
    run_local_tool,
    set_run_local_tools_dir,
)


def test_create_and_run_local_tool(tmp_path):
    set_run_local_tools_dir(str(tmp_path))
    created = create_run_local_tool.invoke({
        "name": "helpers",
        "code": "def add(a, b):\n    return a + b\n",
    })

    assert "Saved run-local tool" in created

    result = run_local_tool.invoke({
        "name": "helpers",
        "function": "add",
        "arguments_json": '{"a": 2, "b": 3}',
    })

    assert result == "5"


def test_create_run_local_tool_rejects_disallowed_import(tmp_path):
    set_run_local_tools_dir(str(tmp_path))
    result = create_run_local_tool.invoke({
        "name": "bad_helper",
        "code": "import socket\n\ndef f():\n    return 1\n",
    })

    assert "Import not allowed" in result


def test_run_local_tool_requires_existing_helper(tmp_path):
    set_run_local_tools_dir(str(tmp_path))
    result = run_local_tool.invoke({
        "name": "missing",
        "function": "add",
        "arguments_json": "{}",
    })

    assert "not found" in result
