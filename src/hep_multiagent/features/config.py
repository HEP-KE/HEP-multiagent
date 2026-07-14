from dataclasses import asdict, dataclass


VALID_WORKER_TYPES = ("data", "compute", "research", "viz")
INTERACTIVE_CONTROLS = ("plan_approval", "python_execution_approval")


@dataclass(frozen=True)
class AgentFeatures:
    plan_approval: bool = False
    python_execution_approval: bool = False
    lesson_memory: bool = True
    report: bool = True
    citations: bool = True
    execution_log: bool = True
    replay_notebook: bool = True
    issue_tracking: bool = True
    run_diagnostics: bool = True
    structured_worker_output: bool = False
    run_local_tool_prototyping: bool = False
    role_prompts: bool = True
    planner_consultations: bool = True
    enabled_workers: tuple[str, ...] = VALID_WORKER_TYPES

    def __post_init__(self):
        enabled = tuple(self.enabled_workers)
        invalid = sorted(set(enabled) - set(VALID_WORKER_TYPES))
        if invalid:
            raise ValueError(f"Unknown worker type(s): {', '.join(invalid)}")
        if not enabled:
            raise ValueError("At least one worker type must be enabled.")
        object.__setattr__(self, "enabled_workers", enabled)

    def experiment_features(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in INTERACTIVE_CONTROLS}
