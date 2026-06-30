# HEP-multiagent

HEP-multiagent is a LangGraph-based research agent for scientific workflows. It turns an open-ended research request into a plan, routes work to specialized workers, calls external MCP tool servers, and writes a final report with execution artifacts.

The package is intentionally an orchestrator, not an MCP server process manager. Start each MCP server independently and pass its HTTP endpoint to the agent.

## Why Use It

- Plan-and-execute workflow for multi-step scientific tasks
- Specialized workers for data access, computation, literature search, and visualization
- MCP integration for domain tools over `streamable_http`
- Optional human approval before execution
- Reproducible outputs: report, citations, execution log, and replay notebook

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set an OpenAI-compatible API key:

```bash
export OPENAI_API_KEY=...
```

## Quickstart

```python
import asyncio
import os

from langchain_openai import ChatOpenAI
from hep_multiagent import Agent


async def main():
    llm = ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=os.environ["OPENAI_API_KEY"],
    )

    agent = await Agent(
        llm=llm,
        mcp_servers=[{"name": "hep-tools", "url": "http://localhost:8000/mcp"}],
    )

    result = await agent.run(
        "Find recent papers on dark matter detection and summarize the main methods.",
        output_dir="./output",
    )
    print(result["final_report"])


asyncio.run(main())
```

There is also a runnable script in `examples/quickstart.py`.

## Demo Notebooks

The root notebooks show the same agent interface with specific MCP servers:

| Notebook | MCP endpoint variable | Purpose |
|----------|-----------------------|---------|
| `demo.ipynb` | `HEP_MCP_SERVER_URL` | General MCP tool-server walkthrough |
| `demo_kb.ipynb` | `KB_MCP_SERVER_URL` | Knowledge-base MCP workflow |
| `demo_mcmc.ipynb` | `MCP_KE_SERVER_URL` | Cosmology/MCMC workflow with `mcp-ke` |
| `demo_microlensing.ipynb` | `MICROLENSING_MCP_SERVER_URL` | Microlensing MCP workflow |

The demo notebooks use ARGO as the LLM backend through LangChain's OpenAI-compatible `ChatOpenAI` client:

```bash
export ARGO_BASE_URL=...
export ARGO_API_KEY=...
export ARGO_MODEL=gpt-5.5
```

Other OpenAI-compatible LLM providers can be used by changing the `ChatOpenAI` configuration cell. Each notebook assumes the MCP server is already running. The notebook connects to the endpoint; it does not install or launch the server.

## MCP Servers

`mcp_servers` is a list of running MCP endpoints:

```python
mcp_servers=[
    {
        "name": "hep-tools",
        "url": "http://localhost:8000/mcp",
        "transport": "streamable_http",
        "headers": {"Authorization": "Bearer ..."},
    }
]
```

Fields:

| Field | Required | Description |
|-------|----------|-------------|
| `url` | yes | HTTP MCP endpoint |
| `name` | no | Stable server name for tracing |
| `transport` | no | `streamable_http` |
| `headers` | no | Request headers for authentication |

Start tool servers outside HEP-multiagent and expose them through one of the supported HTTP transports.

## Outputs

Each run writes to `output_dir`:

| File | Purpose |
|------|---------|
| `execution_log.md` | Planner, worker, and tool-call trace |
| `execution.ipynb` | Replay-oriented notebook for generated code and artifacts |
| `run_diagnostics.json` | Run configuration, timeline, LLM/tool calls, checks, failures, and metrics |
| `references.bib` | BibTeX entries collected through citation tools |
| `report.tex` / `report.pdf` | Final report when LaTeX generation is enabled |

## Feature Toggles

Optional behavior is controlled at initialization with `AgentFeatures`:

```python
from hep_multiagent import Agent, AgentFeatures

features = AgentFeatures(
    plan_approval=False,
    python_execution_approval=False,
    lesson_memory=False,
    report=True,
    citations=True,
    execution_log=True,
    replay_notebook=True,
    issue_tracking=True,
    run_diagnostics=True,
    structured_worker_output=False,
    run_local_tool_prototyping=False,
    role_prompts=True,
)

agent = await Agent(llm=llm, mcp_servers=mcp_servers, features=features)
```

For experiment sweeps, the same settings can be passed as a plain dictionary:

```python
agent = await Agent(llm=llm, features={"lesson_memory": False, "replay_notebook": False})
```

| Toggle | Default | Effect |
|--------|---------|--------|
| `plan_approval` | `False` | Require approval before executing a plan |
| `python_execution_approval` | `False` | Require approval before built-in Python execution |
| `lesson_memory` | `True` | Recall/save lessons from failed worker attempts |
| `report` | `True` | Generate LaTeX/PDF report artifacts |
| `citations` | `True` | Track BibTeX references |
| `execution_log` | `True` | Write `execution_log.md` |
| `replay_notebook` | `True` | Write `execution.ipynb` |
| `issue_tracking` | `True` | Give workers the `log_issue` diagnostic tool |
| `run_diagnostics` | `True` | Write `run_diagnostics.json` for run comparison and troubleshooting |
| `structured_worker_output` | `False` | Require workers to finish with structured artifacts, observations, and limitations |
| `run_local_tool_prototyping` | `False` | Let compute workers create temporary helper tools inside `output_dir/run_local_tools` |
| `role_prompts` | `True` | Use the built-in planner and worker role prompts |

`run_diagnostics.json` is local and deterministic. It records system behavior, not scientific correctness: run configuration, model name, token counts from `tiktoken:cl100k_base`, graph events, worker/tool activity, recovered and unrecovered failures, and checks such as invalid plans, unknown tools, missing artifacts, unsupported citations, and omitted failed steps.

Run-local tool prototyping does not modify repository code or MCP servers. It exposes `create_run_local_tool` and `run_local_tool` only for the current run, so experiments can measure whether temporary helper code improves or disrupts the workflow.

## Architecture

```mermaid
flowchart LR
    Q[User<br/>query] --> P[Planner]
    P --> A{Approval}
    A --> R[Router]
    R --> D[Data<br/>worker]
    R --> C[Compute<br/>worker]
    R --> L[Research<br/>worker]
    R --> V[Viz<br/>worker]
    D --> S[Synthesis]
    C --> S
    L --> S
    V --> S
    S --> O[Report<br/>and artifacts]
```

## Development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Run Sequence

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant A as Agent
    participant M as MCPManager
    participant G as LangGraph
    participant P as Planner
    participant C as Consultants
    participant S as Supervisor
    participant R as Router
    participant W as Worker
    participant T as Tools/MCP
    participant Y as Synthesis
    participant D as Diagnostics
    participant O as Output files

    U->>A: run(query, output_dir)
    A->>O: create output_dir
    A->>D: start run record
    A->>M: load configured MCP endpoints
    M->>T: get tool schemas
    T-->>M: available tools
    M-->>A: tools + source metadata
    A->>G: build graph with features, tools, artifacts, diagnostics

    G->>S: inspect state
    S-->>G: next_action = plan
    G->>P: create plan
    P->>C: optional arxiv/file/data consultation
    C->>T: call available tools when needed
    T-->>C: observations
    C-->>P: planning context
    P-->>G: draft plan
    G->>D: record planner LLM call and plan checks

    alt plan_approval enabled
        G-->>A: await approval
        A->>U: show proposed plan
        U-->>A: approve or feedback
        A->>G: approval update
    end

    loop until plan complete, failed, or stuck
        G->>S: inspect plan status
        S-->>G: next_action = execute
        G->>R: select ready step
        R-->>G: current_step_id
        G->>W: execute assigned worker step
        W->>D: record worker start, tools available, dependency check
        W->>T: call MCP, built-in, or run-local tools
        T-->>W: tool result or error
        W->>D: record LLM/tool calls, failures, recovery signals
        opt run_local_tool_prototyping enabled
            W->>O: create helper under output_dir/run_local_tools
            W->>T: run helper function
        end
        alt structured_worker_output enabled
            W-->>G: status, summary, artifacts, observations, limitations
        else default completion
            W-->>G: status and summary
        end
        G->>O: update log/notebook/artifacts
        G->>D: record step outcome
    end

    G->>Y: synthesize final answer
    Y->>O: write report/references when enabled
    Y-->>G: final_report
    G-->>A: final state
    A->>D: finalize checks and metrics
    D->>O: write run_diagnostics.json
    A-->>U: return result
```
