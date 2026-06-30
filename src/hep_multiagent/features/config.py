from dataclasses import dataclass


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
