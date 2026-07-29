# HEP-multiagent

HEP-multiagent lets scientists ask one question across scientific MCP tools and get a final answer with the run outputs saved in one directory.

## Install

```bash
pip install "git+ssh://git@github.com/HEP-KE/HEP-multiagent.git"
```

Set Argo:

```bash
export ARGO_USER=...
export ARGO_BASE_URL=https://apps-dev.inside.anl.gov/argoapi/v1
export ARGO_MODEL=GPT-5.5
```

## Run With HTTP MCP

Start your MCP server separately, then run:

```bash
hep-multiagent \
  --mcp-url http://127.0.0.1:8000/mcp \
  --output-dir ./output \
  "Use the MCP tools to plot 30 random points."
```

## Run With Stdio MCP

Use stdio when the MCP client should launch the server process:

```bash
hep-multiagent \
  --mcp-command /path/to/mcp-env/bin/python \
  --mcp-args "-m mcp_server --transport stdio" \
  --output-dir ./output \
  "Use the MCP tools to plot 30 random points."
```

## Python API

```python
import asyncio
import os
from langchain_openai import ChatOpenAI
from hep_multiagent import Agent


async def main():
    llm = ChatOpenAI(
        model=os.environ.get("ARGO_MODEL", "GPT-5.5"),
        base_url=os.environ.get("ARGO_BASE_URL", "https://apps-dev.inside.anl.gov/argoapi/v1"),
        api_key=os.environ["ARGO_USER"],
    )
    agent = Agent(
        llm=llm,
        mcp_servers=[{"name": "tools", "url": "http://127.0.0.1:8000/mcp"}],
    )
    result = await agent.run("Use the MCP tools to plot 30 random points.", output_dir="./output")
    print(result["final_report"])


asyncio.run(main())
```

For stdio in Python:

```python
mcp_servers = [{
    "name": "tools",
    "transport": "stdio",
    "command": "/path/to/mcp-env/bin/python",
    "args": ["-m", "mcp_server", "--transport", "stdio"],
}]
```

## MCP Server Config

`mcp_servers` is a list of server dictionaries.

HTTP server:

```python
{"name": "tools", "url": "http://127.0.0.1:8000/mcp"}
```

Stdio server:

```python
{"name": "tools", "transport": "stdio", "command": "/path/to/mcp-env/bin/python", "args": ["-m", "mcp_server", "--transport", "stdio"]}
```

## Outputs

By default, each run writes artifacts under `--output-dir`:

- `run.json`: machine-readable tool calls, artifacts, validations, errors, and step status
- `execution.ipynb`: replay notebook for code and tool calls
- `execution_log.md`: readable run log
- `report.pdf`: formatted report when `pdflatex` is installed
- `report.tex`: LaTeX source for the report
- `references.bib`: citations collected during the run

## Development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
