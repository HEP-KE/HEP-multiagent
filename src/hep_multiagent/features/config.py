from dataclasses import dataclass


@dataclass(frozen=True)
class AgentFeatures:
    report: bool = True
    citations: bool = True
    execution_log: bool = True
    replay_notebook: bool = True
    issue_tracking: bool = True
    structured_worker_output: bool = True
    planner_consultations: bool = False
