# HEP-multiagent

HEP-multiagent is a LangGraph-based research agent for scientific workflows. It turns an open-ended research request into a plan, routes work to specialized workers, calls external MCP tool servers, and writes a final report with execution artifacts.

The package is intentionally an orchestrator, not an MCP server process manager. Start each MCP server independently and pass its HTTP endpoint to the agent.

## Why Use It

- Plan-and-execute workflow for multi-step scientific tasks
- Specialized workers for data access, computation, literature search, and visualization
- MCP integration for domain tools over `streamable_http`
- Optional human approval before execution
- Reproducible outputs: report, citations, execution log, and replay notebook

## Design Boundary

HEP-multiagent uses deterministic graph control for orchestration. `Agent`, `LangGraph`, `AgentState`, `Supervisor`, and `Router` set up runs, maintain state, choose phases, and select ready steps without LLM calls.

LLMs are used only in the planner, optional planning consultants, workers, and synthesis. Prompt text defines role context and output contracts for those LLM phases; it is not the scheduler or state manager. Experimental runs can disable built-in role prompts with `role_prompts=False`, disable planning consultants with `planner_consultations=False`, restrict available worker roles with `enabled_workers`, and compare the resulting behavior through `run_diagnostics.json`.

The LLM boundaries are contract checked. Planner output must parse as JSON and use enabled worker types. Workers must finish through a completion tool, either `final_answer` or, when enabled, `structured_final_answer`. Diagnostics record LLM calls, output contracts, tool calls, invalid plans, missing completion calls, unknown tools, missing artifacts, and citation support checks.

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
    planner_consultations=True,
    enabled_workers=("data", "compute", "research", "viz"),
)

agent = await Agent(llm=llm, mcp_servers=mcp_servers, features=features)
```

For automated experiment sweeps, keep human approval disabled and vary only the system features under study:

```python
agent = await Agent(
    llm=llm,
    features={
        "plan_approval": False,
        "python_execution_approval": False,
        "planner_consultations": False,
    },
)
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
| `planner_consultations` | `True` | Let the planner call arXiv, file, and data consultants before writing the plan |
| `enabled_workers` | `("data", "compute", "research", "viz")` | Restrict which worker types the planner and router may use |

`run_diagnostics.json` is local and deterministic. It records system behavior, not scientific correctness: run configuration, model name, token counts from `tiktoken:cl100k_base`, graph events, worker/tool activity, recovered and unrecovered failures, and checks such as invalid plans, unknown tools, missing artifacts, unsupported citations, and omitted failed steps.

Diagnostics separate `experiment_features` from `interactive_controls`. Human approval gates are recorded for reproducibility, but excluded from the automated comparison feature set because they add human variance.

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
    actor U as User<br/>submits analysis request
    participant A as Agent<br/>initializes each run
    participant M as MCPManager<br/>connects tool servers
    participant T as Tools/MCP<br/>executes tool calls
    participant G as LangGraph<br/>invokes graph nodes
    participant AS as AgentState<br/>stores run state
    participant S as Supervisor<br/>selects graph phase
    box rgb(239, 246, 255) Planner LLM
        participant P as Planner<br/>(LLM)<br/>creates step plan
    end
    box rgb(239, 246, 255) Consultant LLMs
        participant C as Consultants<br/>(LLM)<br/>inform planner only
    end
    participant R as Router<br/>selects ready step
    box rgb(239, 246, 255) Worker LLM
        participant W as Worker<br/>(LLM)<br/>enabled worker role
    end
    box rgb(239, 246, 255) Synthesis LLM
        participant Y as Synthesis<br/>(LLM)<br/>writes final answer
    end
    participant D as Diagnostics<br/>records run behavior
    participant X as Checkpoint DB<br/>persists graph state
    participant O as Output files<br/>stores run artifacts

    U->>A: create Agent(llm, mcp_servers, features)
    opt awaited Agent with MCP servers
        A->>M: load configured MCP endpoints
        M->>T: read tool schemas
        T-->>M: available tools
    end

    U->>A: run(query, output_dir, resume)
    A->>O: create output_dir and configure artifact paths
    opt execution_log enabled
        A->>O: open execution_log.md
    end
    opt run_diagnostics enabled
        A->>D: start run record
    end
    A->>X: open checkpoint.db
    opt lesson_memory enabled
        A->>X: initialize lesson memory tables
    end
    opt MCP servers configured
        A->>M: load configured MCP endpoints
        M->>T: read tool schemas
        T-->>M: available tools
        M-->>A: tools and source metadata
    end
    opt replay_notebook enabled
        A->>O: open execution.ipynb with tool source metadata
    end
    A->>G: build graph with features, tools, writers, checkpoint, diagnostics
    G->>AS: use repo-defined state schema

    alt resume with existing checkpoint state
        A->>X: load prior graph state
        X-->>AS: saved AgentState
        A->>G: continue from checkpoint
    else new run
        A->>AS: initialize query state
        A->>G: start with query message and next_action=plan
    end

    loop graph runs until approval wait, completion, or failure
        G->>AS: read current state
        G->>S: inspect AgentState
        S-->>G: next_action

        alt next_action is plan
            G->>P: create execution plan
            opt planner_consultations enabled
                opt vague scientific terms detected
                    P->>C: arXiv consultation
                    C->>T: search/read research tools
                    T-->>C: research observations
                    C-->>P: criteria and citation context
                end
                opt local file paths detected
                    P->>C: file consultation
                    C->>T: inspect file through available tools
                    T-->>C: file structure observations
                    C-->>P: columns and data context
                end
                opt MCP tools available and no file paths
                    P->>C: data-source consultation
                    C->>T: inspect available MCP tools
                    T-->>C: source observations
                    C-->>P: data access context
                end
            end
            P-->>G: plan or planner error
            G->>AS: merge plan update
            G->>D: record planner call and validate plan
            G->>S: return to supervisor
        end

        alt next_action is await_approval
            G-->>A: await approval
            A->>U: show proposed plan
            U-->>A: approve or feedback
            A->>G: submit approval update
            G->>AS: merge approval update
            G->>S: resume at supervisor
        end

        alt next_action is execute
            G->>R: select ready step
            R-->>G: current_step_id
            G->>AS: mark step running
            G->>W: execute routed enabled worker step
            W->>D: record worker start, tools available, dependency check
            opt lesson_memory enabled
                W->>X: recall lessons for worker type
            end
            loop worker iterations until final answer, retry limit, or failure
                W->>W: choose MCP, built-in, or completion tool
                W->>T: call selected MCP or built-in tool
                T-->>W: result or error
                W->>D: record LLM call, tool call, artifacts, failures, recovery signals
                opt run_local_tool_prototyping enabled for compute worker
                    W->>O: create helper under output_dir/run_local_tools
                    W->>T: run helper function
                end
            end
            alt structured_worker_output enabled
                W-->>G: status, summary, artifacts, observations, limitations
            else default completion
                W-->>G: status and summary
            end
            G->>AS: merge step result
            G->>X: save graph checkpoint
            G->>O: update log, notebook, and artifacts
            opt lesson_memory enabled
                G->>X: save lesson from failed worker attempt
            end
            G->>D: record step outcome
            G->>S: return to supervisor
        end

        alt next_action is synthesize
            G->>Y: synthesize final answer
            Y->>O: read step outputs, artifacts, and references
            Y-->>G: final report text
            G->>AS: merge final report
            opt report enabled
                Y->>Y: generate LaTeX report body
                Y->>O: write report artifacts
            end
            opt citations enabled
                Y->>O: export references.bib
            end
            G-->>A: final state
        end
    end

    opt run_diagnostics enabled
        alt run completed
            A->>D: finalize checks and metrics
            D->>O: write run_diagnostics.json
        else run failed
            A->>D: record failure and finalize diagnostics
            D->>O: write run_diagnostics.json
        end
    end
    A->>O: close log and notebook
    A->>M: close MCP connections
    A-->>U: return result
```
