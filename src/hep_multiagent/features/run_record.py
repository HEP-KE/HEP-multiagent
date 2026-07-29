import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, NonNegativeInt


SECRET_KEYS = ("authorization", "cookie", "key", "password", "secret", "token")


class ArtifactRecord(BaseModel):
    path: str = Field(min_length=1)
    exists: bool
    size: NonNegativeInt | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    summary: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    worker_type: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    result: str
    error: str | None = None
    source: dict[str, Any] | None = None
    code: str | None = None
    artifacts: list[ArtifactRecord] = Field(default_factory=list)


class ClaimRecord(BaseModel):
    step_id: str = Field(min_length=1)
    worker_type: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class StepRecord(BaseModel):
    step_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    worker_type: str = Field(min_length=1)
    status: Literal["pending", "ready", "running", "completed", "failed", "blocked"]
    error: str | None = None
    tool_calls: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)


class ValidationRecord(BaseModel):
    name: str = Field(min_length=1)
    passed: bool
    details: str = ""


class CitationRecord(BaseModel):
    key: str = Field(min_length=1)
    arxiv_id: str | None = None
    title: str | None = None
    quotes: list[str] = Field(default_factory=list)


class RunRecord(BaseModel):
    schema_version: int = 1
    query: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    status: Literal["running", "completed", "failed"] = "running"
    error: str | None = None
    environment: dict[str, Any] = Field(default_factory=dict)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[StepRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    citations: list[CitationRecord] = Field(default_factory=list)
    validations: list[ValidationRecord] = Field(default_factory=list)


class RunRecorder:
    def __init__(self):
        self.path: Path | None = None
        self.record: RunRecord | None = None
        self._tool_call_count = 0

    def start(
        self,
        query: str,
        output_dir: str,
        mcp_servers: list[dict[str, Any]] | None = None,
        tools: list | None = None,
    ) -> None:
        self.path = Path(output_dir) / "run.json"
        self.record = RunRecord(
            query=query,
            output_dir=str(Path(output_dir).resolve()),
            environment=_environment(),
            mcp_servers=[_redact_secrets(server) for server in (mcp_servers or [])],
            tools=[_tool_schema(tool) for tool in (tools or [])],
        )
        self.save()

    def set_tools(self, tools: list) -> None:
        self.record.tools = [_tool_schema(tool) for tool in tools]
        self.save()

    def tool_call(
        self,
        step: dict,
        tool_name: str,
        args: dict,
        result: str,
        artifact_paths: list[str],
        source: dict[str, Any] | None = None,
    ) -> None:
        artifacts = [self.artifact(path) for path in artifact_paths]
        error = result if result.startswith("Error:") else None
        self._tool_call_count += 1
        self.record.tool_calls.append(ToolCallRecord(
            id=f"tc{self._tool_call_count}",
            step_id=step["id"],
            worker_type=step["worker_type"],
            tool_name=tool_name,
            args=_redact_secrets(args),
            result=result,
            error=error,
            source=_redact_secrets(source) if source else None,
            code=args.get("code") if tool_name == "execute_python" else None,
            artifacts=artifacts,
        ))
        self._record_claims(step, args)
        self.save()

    def finish(self, state: dict | None, error: str | None = None) -> None:
        state = state or {}
        plan = state.get("plan") or {}
        self.record.steps = [self.step(step) for step in plan.get("steps", [])]
        self.record.issues = state.get("tool_issues", [])
        self.record.error = error or state.get("error")
        self.record.citations = _read_citations(Path(self.record.output_dir) / "references.bib")
        self.record.status = (
            "failed"
            if self.record.error or any(step.status == "failed" for step in self.record.steps)
            else "completed"
        )
        self.record.validations = validate_run(self.record)
        self.save()

    def step(self, step: dict) -> StepRecord:
        tool_calls = [call.id for call in self.record.tool_calls if call.step_id == step["id"]]
        return StepRecord(
            step_id=step["id"],
            name=step["name"],
            worker_type=step["worker_type"],
            status=step["status"],
            error=step.get("error"),
            tool_calls=tool_calls,
            artifacts=[self.artifact(path) for path in step.get("artifacts", [])],
        )

    def _record_claims(self, step: dict, args: dict) -> None:
        claims = args.get("claims", [])
        evidence = args.get("evidence", [])
        if not isinstance(claims, list):
            return
        if not isinstance(evidence, list):
            evidence = []
        self.record.claims.extend(
            ClaimRecord(
                step_id=step["id"],
                worker_type=step["worker_type"],
                claim=claim,
                evidence=evidence,
            )
            for claim in claims
            if isinstance(claim, str) and claim.strip()
        )

    def artifact(self, path: str) -> ArtifactRecord:
        artifact_path = Path(path)
        if not artifact_path.is_absolute():
            artifact_path = Path(self.record.output_dir) / artifact_path
        if not artifact_path.exists() or not artifact_path.is_file():
            return ArtifactRecord(path=str(artifact_path), exists=False)
        return ArtifactRecord(
            path=str(artifact_path),
            exists=True,
            size=artifact_path.stat().st_size,
            sha256=_sha256(artifact_path),
            summary=_artifact_summary(artifact_path),
        )

    def save(self) -> None:
        self.path.write_text(self.record.model_dump_json(indent=2) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_summary(path: Path) -> dict[str, Any]:
    try:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return _csv_summary(path)
        if suffix == ".png":
            return _png_summary(path)
        if suffix in {".jpg", ".jpeg"}:
            return _jpeg_summary(path)
        if suffix in {".txt", ".md", ".json", ".yaml", ".yml"}:
            return _text_summary(path)
        return {}
    except Exception as exc:
        return {"summary_error": f"{type(exc).__name__}: {exc}"}


def _environment() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "package_version": _package_version(),
    }


def _package_version() -> str | None:
    try:
        return importlib.metadata.version("hep-multiagent")
    except importlib.metadata.PackageNotFoundError:
        return None


def _tool_schema(tool) -> dict[str, Any]:
    schema = None
    args_schema = getattr(tool, "args_schema", None)
    if isinstance(args_schema, dict):
        schema = args_schema
    elif args_schema and hasattr(args_schema, "model_json_schema"):
        schema = args_schema.model_json_schema()
    elif args_schema and hasattr(args_schema, "schema"):
        schema = args_schema.schema()
    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", ""),
        "args_schema": schema,
    }


def _csv_summary(path: Path) -> dict[str, Any]:
    with path.open(newline="") as file:
        reader = csv.DictReader(file)
        columns = reader.fieldnames or []
        stats = {column: _empty_column_stats() for column in columns}
        rows = 0
        for row in reader:
            rows += 1
            for column in columns:
                _update_column_stats(stats[column], row.get(column, ""))
    column_stats = {
        column: _finish_column_stats(values)
        for column, values in stats.items()
        if values["count"] or values["missing"] or values["non_numeric"]
    }
    return {
        "type": "csv",
        "rows": rows,
        "columns": columns,
        "column_count": len(columns),
        "column_stats": column_stats,
    }


def _empty_column_stats() -> dict[str, Any]:
    return {
        "count": 0,
        "finite_count": 0,
        "missing": 0,
        "non_numeric": 0,
        "non_finite": 0,
        "min": None,
        "max": None,
        "sum": 0.0,
    }


def _update_column_stats(stats: dict[str, Any], value: str | None) -> None:
    value = "" if value is None else value.strip()
    if value == "":
        stats["missing"] += 1
        return
    try:
        number = float(value)
    except ValueError:
        stats["non_numeric"] += 1
        return
    stats["count"] += 1
    if not math.isfinite(number):
        stats["non_finite"] += 1
        return
    stats["finite_count"] += 1
    stats["sum"] += number
    stats["min"] = number if stats["min"] is None else min(stats["min"], number)
    stats["max"] = number if stats["max"] is None else max(stats["max"], number)


def _finish_column_stats(stats: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in stats.items() if key != "sum"}
    result["mean"] = stats["sum"] / stats["finite_count"] if stats["finite_count"] else None
    return result


def _png_summary(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        header = file.read(24)
    if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        return {"type": "png", "width": width, "height": height}
    return {"type": "png"}


def _jpeg_summary(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            break
        marker = data[index + 1]
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if marker in {0xC0, 0xC2}:
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            return {"type": "jpeg", "width": width, "height": height}
        index += 2 + length
    return {"type": "jpeg"}


def _text_summary(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    return {"type": path.suffix.lower().lstrip("."), "lines": len(text.splitlines()), "characters": len(text)}


def _redact_secrets(value: Any, key: str = "") -> Any:
    if any(secret in key.lower() for secret in SECRET_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return {k: _redact_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _read_citations(bib_path: Path) -> list[CitationRecord]:
    if not bib_path.exists():
        return []
    content = bib_path.read_text(errors="replace")
    citations = []
    for match in re.finditer(r"@\w+\{([^,]+),(.+?)\n\}", content, re.DOTALL):
        body = match.group(2)
        citations.append(CitationRecord(
            key=match.group(1).strip(),
            arxiv_id=_bib_field(body, "eprint"),
            title=_bib_field(body, "title"),
            quotes=_bib_quotes(_bib_field(body, "note")),
        ))
    return citations


def _bib_field(body: str, field: str) -> str | None:
    match = re.search(rf"{field}\s*=\s*\{{(.+?)\}}", body, re.DOTALL)
    return match.group(1).strip() if match else None


def _bib_quotes(note: str | None) -> list[str]:
    if not note:
        return []
    try:
        quotes = json.loads(note)
    except json.JSONDecodeError:
        return []
    return [quote for quote in quotes if isinstance(quote, str)] if isinstance(quotes, list) else []


def validate_run(record: RunRecord) -> list[ValidationRecord]:
    step_ids = {step.step_id for step in record.steps}
    return [
        _validate_tool_steps(record, step_ids),
        _validate_artifacts(record),
        _validate_claims(record),
        _validate_citations(record),
        _validate_failed_steps(record),
        _validate_status(record),
    ]


def _validate_tool_steps(record: RunRecord, step_ids: set[str]) -> ValidationRecord:
    missing = sorted({call.step_id for call in record.tool_calls if call.step_id not in step_ids})
    return ValidationRecord(
        name="tool_calls_reference_steps",
        passed=not missing,
        details="" if not missing else f"Tool calls reference unknown steps: {', '.join(missing)}",
    )


def _validate_artifacts(record: RunRecord) -> ValidationRecord:
    artifacts = [artifact for step in record.steps for artifact in step.artifacts]
    artifacts.extend(artifact for call in record.tool_calls for artifact in call.artifacts)
    missing = sorted({artifact.path for artifact in artifacts if not artifact.exists})
    unhashed = sorted({artifact.path for artifact in artifacts if artifact.exists and not artifact.sha256})
    issues = []
    if missing:
        issues.append(f"Missing artifacts: {', '.join(missing)}")
    if unhashed:
        issues.append(f"Existing artifacts without sha256: {', '.join(unhashed)}")
    return ValidationRecord(
        name="artifacts_exist_and_are_hashed",
        passed=not issues,
        details="; ".join(issues),
    )


def _validate_claims(record: RunRecord) -> ValidationRecord:
    missing = [claim.claim for claim in record.claims if not claim.evidence]
    return ValidationRecord(
        name="claims_have_evidence",
        passed=not missing,
        details="" if not missing else f"Claims missing evidence: {'; '.join(missing)}",
    )


def _validate_citations(record: RunRecord) -> ValidationRecord:
    incomplete = [
        citation.key
        for citation in record.citations
        if not citation.arxiv_id or not citation.title or not citation.quotes
    ]
    return ValidationRecord(
        name="citations_have_source_quotes",
        passed=not incomplete,
        details="" if not incomplete else f"Citations missing arxiv_id, title, or quotes: {', '.join(incomplete)}",
    )


def _validate_failed_steps(record: RunRecord) -> ValidationRecord:
    failed_without_error = sorted(step.step_id for step in record.steps if step.status == "failed" and not step.error)
    return ValidationRecord(
        name="failed_steps_have_errors",
        passed=not failed_without_error,
        details="" if not failed_without_error else f"Failed steps missing errors: {', '.join(failed_without_error)}",
    )


def _validate_status(record: RunRecord) -> ValidationRecord:
    has_failed_step = any(step.status == "failed" for step in record.steps)
    expected = "failed" if record.error or has_failed_step else "completed"
    return ValidationRecord(
        name="run_status_matches_steps",
        passed=record.status == expected,
        details="" if record.status == expected else f"Expected {expected}, got {record.status}",
    )
