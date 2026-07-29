import asyncio
import json
import os
from pathlib import Path

import pytest
from langchain_openai import ChatOpenAI

from hep_multiagent import Agent, AgentFeatures


def live_mcp_tests_enabled() -> bool:
    return os.environ.get("RUN_MULTIAGENT_MCP_TESTS") == "1"


def _has_real_value(name: str) -> bool:
    value = os.environ.get(name, "").strip()
    return bool(value and value.lower() not in {"dummy", "test", "..."})


def llm():
    if not (_has_real_value("ARGO_BASE_URL") and _has_real_value("ARGO_USER")):
        pytest.skip("Set real ARGO_BASE_URL and ARGO_USER for live agent tests.")
    return ChatOpenAI(
        model=os.environ.get("ARGO_MODEL", "gpt-5.5"),
        base_url=os.environ["ARGO_BASE_URL"],
        api_key=os.environ["ARGO_USER"],
    )


def headers(env_name: str) -> dict | None:
    value = os.environ.get(env_name)
    return json.loads(value) if value else None


async def run_server_test(
    *,
    base_dir: Path,
    server_name: str,
    url_env: str,
    default_url: str | None,
    query: str,
    skip_without_url: str,
):
    url = os.environ.get(url_env, default_url)
    if not url:
        pytest.skip(skip_without_url)

    server = {"name": server_name, "url": url}
    auth_headers = headers(f"{url_env}_HEADERS_JSON")
    if auth_headers:
        server["headers"] = auth_headers

    output_dir = base_dir / "output"

    features = AgentFeatures(
        report=False,
        citations=False,
        replay_notebook=True,
        execution_log=True,
    )
    agent = Agent(llm=llm(), mcp_servers=[server], features=features)
    result = await agent.run(query, output_dir=str(output_dir))

    assert result["final_report"]
    assert (output_dir / "execution_log.md").exists()
    assert (output_dir / "execution.ipynb").exists()


def run_live_server_test(**kwargs):
    asyncio.run(run_server_test(**kwargs))
