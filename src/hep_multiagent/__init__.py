__all__ = ["Agent", "AgentFeatures"]


def __getattr__(name):
    if name == "Agent":
        from .agent import Agent

        return Agent
    if name == "AgentFeatures":
        from .features.config import AgentFeatures

        return AgentFeatures
    raise AttributeError(f"module 'hep_multiagent' has no attribute {name!r}")
