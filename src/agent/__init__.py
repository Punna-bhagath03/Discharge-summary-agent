"""
Public API for src/agent.

Phase 9 delivers AgentStateManager.  Phases 10–12 deliver Planner, Executor,
TraceSystem, and AgentLoop.  wiring.build_agent_loop() composes the full loop.

Architecture reference — architecture.md §6.
"""

from src.agent.agent_loop import AgentLoop, AgentRunResult
from src.agent.executor import Executor
from src.agent.planner import Planner, PlannerDecision
from src.agent.state_manager import AgentStateManager
from src.agent.trace_system import TraceSystem
from src.agent.wiring import build_agent_loop

__all__ = [
    "AgentLoop",
    "AgentRunResult",
    "AgentStateManager",
    "Executor",
    "Planner",
    "PlannerDecision",
    "TraceSystem",
    "build_agent_loop",
]
