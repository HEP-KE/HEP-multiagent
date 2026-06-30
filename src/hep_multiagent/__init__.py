__all__ = ["Agent"]


def __getattr__(name):
    if name == "Agent":
        from .agent import Agent

        return Agent
    raise AttributeError(f"module 'hep_multiagent' has no attribute {name!r}")
