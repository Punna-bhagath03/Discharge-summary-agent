"""
Public API for src/agent.

Phase 9 delivers AgentStateManager — the sole owner of AgentState
transitions.  All other agent components (Planner, Executor, Trace System)
are implemented in later phases and will be exported from this module as
they land.

Architecture reference — architecture.md §6:
  'src/agent/ — Agent State, Planner, Executor, Trace System, Agent Loop.'
"""

from src.agent.state_manager import AgentStateManager

__all__ = [
    "AgentStateManager",
]
