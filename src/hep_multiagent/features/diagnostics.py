import json
import os
import platform
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import tiktoken


FAILURE_TYPES = {
    "agent_workflow_failure",
    "artifact_hallucination",
    "citation_hallucination",
    "final_report_omitted_failure",
    "llm_connection_failure",
    "llm_instruction_failure",
    "llm_invalid_output",
    "llm_tool_hallucination",
    "mcp_server_failure",
    "python_execution_failure",
    "remote_api_failure",
    "report_generation_failure",
    "tool_argument_failure",
    "tool_runtime_failure",
    "user_interruption",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _model_name(llm: Any) -> str:
    for attr in ("model_name", "model", "model_id", "deployment_name"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)
    return type(llm).__name__


def _provider_name(llm: Any) -> str:
    module = type(llm).__module__.split(".")[0]
    return module or type(llm).__name__


class TokenCounter:
    encoding_name = "cl100k_base"

    def __init__(self):
        self.encoding = tiktoken.get_encoding(self.encoding_name)

    def count_text(self, text: Any) -> int:
        if text is None:
            return 0
        return len(self.encoding.encode(str(text)))

    def count_messages(self, messages: List[Any]) -> int:
        total = 0
        for msg in messages:
            total += self.count_text(getattr(msg, "content", msg))
        return total


class RunDiagnostics:
    def __init__(self, query: str, output_dir: str, llm: Any, features: Any, mcp_servers: Any = None):
        self.output_dir = output_dir
        self.path = os.path.join(output_dir, "run_diagnostics.json")
        self.model = _model_name(llm)
        self.provider = _provider_name(llm)
        self.counter = TokenCounter()
        self._finalized = False
        self._agent_start_times: Dict[str, float] = {}
        self.data = {
            "run": {
                "run_id": f"run-{uuid.uuid4().hex[:12]}",
                "query": query,
                "started_at": utc_now(),
                "ended_at": None,
                "runtime_seconds": None,
                "status": "running",
            },
            "configuration": {
                "model": self.model,
                "llm_provider": self.provider,
                "token_count_method": f"tiktoken:{TokenCounter.encoding_name}",
                "python_version": platform.python_version(),
                "features": asdict(features),
                "mcp_servers": self._normalize_mcp_servers(mcp_servers),
                "available_tools": [],
                "worker_types": [],
            },
            "timeline": [],
            "agents": {},
            "structured_outputs": {
                "enabled": bool(getattr(features, "structured_worker_output", False)),
                "worker_outputs": [],
            },
            "llm_calls": [],
            "tool_calls": [],
            "checks": {
                "plan_json_valid": None,
                "plan_structure_valid": None,
                "worker_types_valid": None,
                "step_dependencies_valid": None,
                "dependency_order_valid": True,
                "all_executed_steps_finished": None,
                "workers_called_final_answer": None,
                "claimed_artifacts_exist": None,
                "citations_supported_by_references": None,
                "final_report_mentions_failed_steps": None,
            },
            "failures": [],
            "metrics": {},
        }

    def _normalize_mcp_servers(self, mcp_servers: Any) -> List[dict]:
        if not mcp_servers:
            return []
        if isinstance(mcp_servers, str):
            return [{"name": "mcp", "url": mcp_servers, "transport": "streamable_http"}]
        servers = []
        for server in mcp_servers:
            if isinstance(server, dict):
                servers.append({
                    "name": server.get("name"),
                    "url": server.get("url"),
                    "transport": server.get("transport", "streamable_http"),
                })
        return servers

    def configure_tools(self, tools: List[Any], tool_sources: Dict[str, dict], worker_types: List[str]) -> None:
        self.data["configuration"]["available_tools"] = [
            {"name": t.name, "source": tool_sources.get(t.name, {}).get("name", "unknown")}
            for t in tools
        ]
        self.data["configuration"]["worker_types"] = list(worker_types)

    def event(self, component: str, event: str, details: str = "") -> None:
        self.data["timeline"].append({
            "timestamp": utc_now(),
            "component": component,
            "event": event,
            "details": details,
        })

    def ensure_agent(self, name: str, tools_available: Optional[List[str]] = None) -> dict:
        agents = self.data["agents"]
        if name not in agents:
            agents[name] = {
                "status": "not_used",
                "assigned_step_ids": [],
                "tools_available": [],
                "tools_used": [],
                "artifacts_created": [],
                "final_answer_produced": None,
                "structured_output_valid": None,
                "recovered_failure_count": 0,
                "unrecovered_failure_count": 0,
            }
        if tools_available is not None:
            agents[name]["tools_available"] = sorted(set(tools_available))
        return agents[name]

    @contextmanager
    def agent_timer(self, name: str):
        self.ensure_agent(name)
        self._agent_start_times[name] = time.perf_counter()
        try:
            yield
        finally:
            start = self._agent_start_times.pop(name, None)
            if start is not None:
                elapsed = time.perf_counter() - start
                metrics = self.data.setdefault("metrics", {})
                runtime = metrics.setdefault("runtime_by_agent_seconds", {})
                runtime[name] = round(runtime.get(name, 0.0) + elapsed, 3)

    async def record_llm_call(self, agent: str, purpose: str, llm: Any, messages: List[Any], output_contract: str, call):
        started = time.perf_counter()
        input_tokens = self.counter.count_messages(messages)
        try:
            response = await call()
        except Exception as e:
            runtime = time.perf_counter() - started
            self.data["llm_calls"].append({
                "agent": agent,
                "purpose": purpose,
                "model": _model_name(llm),
                "input_tokens": input_tokens,
                "output_tokens": 0,
                "total_tokens": input_tokens,
                "runtime_seconds": round(runtime, 3),
                "status": "failed",
                "tool_calls_requested": [],
                "output_contract": output_contract,
                "problem": str(e),
            })
            self.failure("llm_connection_failure", agent, None, f"{type(e).__name__}: {e}", False, "llm_call_failed")
            raise

        runtime = time.perf_counter() - started
        content = getattr(response, "content", "")
        tool_calls = [tc.get("name") for tc in getattr(response, "tool_calls", []) if isinstance(tc, dict)]
        output_tokens = self.counter.count_text(content)
        self.data["llm_calls"].append({
            "agent": agent,
            "purpose": purpose,
            "model": _model_name(llm),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "runtime_seconds": round(runtime, 3),
            "status": "success",
            "tool_calls_requested": tool_calls,
            "output_contract": output_contract,
            "problem": None,
        })
        return response

    def mark_last_llm_contract(self, agent: str, purpose: str, output_contract: str, problem: str = None) -> None:
        for call in reversed(self.data["llm_calls"]):
            if call["agent"] == agent and call["purpose"] == purpose:
                call["output_contract"] = output_contract
                call["problem"] = problem
                return

    def record_tool_call(
        self,
        agent: str,
        step_id: Optional[str],
        tool: str,
        source: str,
        runtime_seconds: float,
        status: str,
        error_type: Optional[str],
        error_message: Optional[str],
        artifacts_detected: List[str],
    ) -> None:
        self.ensure_agent(agent)
        self.data["agents"][agent]["tools_used"] = sorted(set(self.data["agents"][agent]["tools_used"] + [tool]))
        self.data["tool_calls"].append({
            "agent": agent,
            "step_id": step_id,
            "tool": tool,
            "source": source,
            "runtime_seconds": round(runtime_seconds, 3),
            "status": status,
            "error_type": error_type,
            "error_message": error_message,
            "artifacts_detected": artifacts_detected,
        })

    def record_worker_output(self, agent: str, step_id: str, output: dict, valid: bool) -> None:
        self.ensure_agent(agent)
        self.data["agents"][agent]["structured_output_valid"] = valid
        self.data["structured_outputs"]["worker_outputs"].append({
            "agent": agent,
            "step_id": step_id,
            "status": output.get("status"),
            "summary": output.get("summary"),
            "artifacts": output.get("artifacts", []),
            "observations": output.get("observations", []),
            "limitations": output.get("limitations", []),
        })

    def assign_step(self, agent: str, step_id: str, tools_available: List[str]) -> None:
        record = self.ensure_agent(agent, tools_available)
        record["status"] = "running"
        if step_id not in record["assigned_step_ids"]:
            record["assigned_step_ids"].append(step_id)

    def finish_agent_step(self, agent: str, status: str, artifacts: List[str], final_answer_produced: bool) -> None:
        record = self.ensure_agent(agent)
        record["status"] = status
        record["artifacts_created"] = sorted(set(record["artifacts_created"] + artifacts))
        record["final_answer_produced"] = final_answer_produced

    def failure(self, failure_type: str, agent: str, step_id: Optional[str], evidence: str, recovered: bool, impact: str) -> None:
        if failure_type not in FAILURE_TYPES:
            failure_type = "agent_workflow_failure"
        self.ensure_agent(agent)
        key = "recovered_failure_count" if recovered else "unrecovered_failure_count"
        self.data["agents"][agent][key] += 1
        self.data["failures"].append({
            "type": failure_type,
            "agent": agent,
            "step_id": step_id,
            "evidence": evidence,
            "recovered": recovered,
            "impact": impact,
        })

    def mark_step_recovered(self, agent: str, step_id: str) -> None:
        record = self.ensure_agent(agent)
        for failure in self.data["failures"]:
            if failure["agent"] == agent and failure["step_id"] == step_id and not failure["recovered"]:
                failure["recovered"] = True
                failure["impact"] = "none"
                record["unrecovered_failure_count"] = max(0, record["unrecovered_failure_count"] - 1)
                record["recovered_failure_count"] += 1

    def validate_plan(self, plan: Optional[dict], worker_types: List[str]) -> None:
        checks = self.data["checks"]
        if not plan:
            checks["plan_structure_valid"] = False
            return
        steps = plan.get("steps", [])
        ids = [s.get("id") for s in steps]
        unique_ids = len(ids) == len(set(ids))
        known_workers = all(s.get("worker_type") in worker_types for s in steps)
        deps_valid = all(dep in ids for s in steps for dep in s.get("depends_on", []))
        required = all(s.get("id") and s.get("name") and s.get("worker_type") and s.get("description") for s in steps)
        checks["plan_structure_valid"] = bool(steps and unique_ids and required)
        checks["worker_types_valid"] = known_workers
        checks["step_dependencies_valid"] = deps_valid
        if not known_workers:
            self.failure("agent_workflow_failure", "planner", None, "Planner produced an unknown worker type.", False, "invalid_plan")
        if not deps_valid:
            self.failure("agent_workflow_failure", "planner", None, "Planner produced a dependency on a nonexistent step.", False, "invalid_plan")

    def validate_dependency_order(self, plan: Optional[dict], step_id: str) -> None:
        if not plan or not step_id:
            return
        steps = plan.get("steps", [])
        current = next((s for s in steps if s.get("id") == step_id), None)
        if not current:
            return
        completed = {s["id"] for s in steps if s.get("status") == "completed"}
        missing = [dep for dep in current.get("depends_on", []) if dep not in completed]
        if missing:
            self.data["checks"]["dependency_order_valid"] = False
            self.failure("agent_workflow_failure", f"{current.get('worker_type')}_worker", step_id, f"Step ran before dependencies completed: {missing}", False, "invalid_execution_order")

    def finalize(self, status: str, result: Optional[dict] = None) -> None:
        if self._finalized:
            return
        self._finalized = True
        self.data["run"]["ended_at"] = utc_now()
        start = datetime.fromisoformat(self.data["run"]["started_at"])
        end = datetime.fromisoformat(self.data["run"]["ended_at"])
        self.data["run"]["runtime_seconds"] = round((end - start).total_seconds(), 3)
        self.data["run"]["status"] = status
        self._final_checks(result)
        self._metrics(result)
        self.write()

    def _final_checks(self, result: Optional[dict]) -> None:
        plan = (result or {}).get("plan") if result else None
        steps = plan.get("steps", []) if plan else []
        checks = self.data["checks"]
        executed = [s for s in steps if s.get("status") in ("completed", "failed")]
        checks["all_executed_steps_finished"] = all(s.get("status") in ("completed", "failed") for s in executed)
        worker_steps = [s for s in executed if s.get("worker_type")]
        checks["workers_called_final_answer"] = all(
            self.data["agents"].get(f"{s['worker_type']}_worker", {}).get("final_answer_produced") is True
            for s in worker_steps
        ) if worker_steps else None
        checks["claimed_artifacts_exist"] = self._claimed_artifacts_exist(steps)
        checks["citations_supported_by_references"] = self._citations_supported((result or {}).get("final_report", ""))
        checks["final_report_mentions_failed_steps"] = self._report_mentions_failures(steps, (result or {}).get("final_report", ""))

    def _claimed_artifacts_exist(self, steps: List[dict]) -> bool:
        ok = True
        for step in steps:
            for artifact in step.get("artifacts", []):
                candidates = [artifact]
                if not os.path.isabs(artifact):
                    candidates.append(os.path.join(self.output_dir, artifact))
                    candidates.append(os.path.abspath(artifact))
                if not any(os.path.exists(path) for path in candidates):
                    ok = False
                    self.failure("artifact_hallucination", f"{step.get('worker_type')}_worker", step.get("id"), f"Claimed artifact does not exist: {artifact}", False, "missing_expected_artifact")
        return ok

    def _citations_supported(self, final_report: str) -> Optional[bool]:
        if not final_report:
            return None
        cited = set(re.findall(r"arXiv:(\d{4}\.\d{4,5})", final_report))
        if not cited:
            return True
        bib_path = os.path.join(self.output_dir, "references.bib")
        if not os.path.exists(bib_path):
            for arxiv_id in sorted(cited):
                self.failure("citation_hallucination", "synthesis", None, f"Final report cited arXiv:{arxiv_id}, but references.bib does not exist.", False, "unsupported_citation")
            return False
        bib = open(bib_path, encoding="utf-8").read()
        missing = [arxiv_id for arxiv_id in cited if arxiv_id not in bib]
        for arxiv_id in missing:
            self.failure("citation_hallucination", "synthesis", None, f"Final report cited arXiv:{arxiv_id}, but it was not present in references.bib.", False, "unsupported_citation")
        return not missing

    def _report_mentions_failures(self, steps: List[dict], final_report: str) -> Optional[bool]:
        failed = [s for s in steps if s.get("status") == "failed"]
        if not failed:
            return True
        if not final_report:
            return False
        ok = True
        report_lower = final_report.lower()
        for step in failed:
            evidence = str(step.get("error") or step.get("name") or "").lower()
            if evidence and evidence[:40] not in report_lower and step.get("name", "").lower() not in report_lower:
                ok = False
                self.failure("final_report_omitted_failure", "synthesis", step.get("id"), f"Final report did not mention failed step: {step.get('name')}", False, "hidden_failed_step")
        return ok

    def _metrics(self, result: Optional[dict]) -> None:
        metrics = self.data["metrics"]
        tokens_by_agent: Dict[str, int] = {}
        for call in self.data["llm_calls"]:
            tokens_by_agent[call["agent"]] = tokens_by_agent.get(call["agent"], 0) + call["total_tokens"]
        metrics["total_tokens"] = sum(tokens_by_agent.values())
        metrics["tokens_by_agent"] = tokens_by_agent
        metrics.setdefault("runtime_by_agent_seconds", {})
        metrics["tool_calls_total"] = len(self.data["tool_calls"])
        metrics["tool_calls_failed"] = sum(1 for c in self.data["tool_calls"] if c["status"] == "failed")
        metrics["run_local_tools_created"] = sum(1 for c in self.data["tool_calls"] if c["tool"] == "create_run_local_tool" and c["status"] == "success")
        metrics["run_local_tool_executions"] = sum(1 for c in self.data["tool_calls"] if c["tool"] == "run_local_tool")
        metrics["llm_calls_total"] = len(self.data["llm_calls"])
        metrics["llm_calls_failed"] = sum(1 for c in self.data["llm_calls"] if c["status"] == "failed")
        metrics["failures_total"] = len(self.data["failures"])
        metrics["failures_recovered"] = sum(1 for f in self.data["failures"] if f["recovered"])
        metrics["failures_unrecovered"] = sum(1 for f in self.data["failures"] if not f["recovered"])
        metrics["final_report_produced"] = bool((result or {}).get("final_report"))
        structured = self.data["structured_outputs"]["worker_outputs"]
        metrics["structured_worker_outputs_valid"] = all(
            self.data["agents"].get(o["agent"], {}).get("structured_output_valid") is True for o in structured
        ) if structured else None

    def write(self) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
