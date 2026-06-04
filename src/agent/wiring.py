"""
Agent loop wiring — constructs Planner, Executor, TraceSystem, and AgentLoop.

Architecture reference — architecture.md §6:
  Composition root for src/agent/ and src/services/ agent-loop components.
"""

from __future__ import annotations

from src.agent.agent_loop import AgentLoop
from src.agent.executor import Executor
from src.agent.planner import Planner
from src.agent.state_manager import AgentStateManager
from src.agent.trace_system import TraceSystem
from src.services.conflict_detection_service import ConflictDetectionService
from src.services.medication_reconciliation_service import (
    MedicationReconciliationService,
)
from src.services.pending_results_service import PendingResultsService
from src.services.summary_generation_service import SummaryGenerationService
from src.storage.storage_service import StorageService


def build_agent_loop(
    storage: StorageService | None = None,
    *,
    max_iterations: int = 10,
    low_confidence_threshold: float = 0.75,
    readiness_threshold: float = 0.85,
) -> AgentLoop:
    """
    Construct a fully wired AgentLoop with default service instances.

    Parameters
    ----------
    storage:
        StorageService instance.  A new in-memory instance is created when None.
    max_iterations:
        MAX_AGENT_ITERATIONS bound (FR-33a).
    low_confidence_threshold:
        Passed to AgentStateManager for low_confidence_pages refresh (SR-18).
    readiness_threshold:
        Planner readiness threshold for summary_ready.
    """
    store = storage if storage is not None else StorageService()
    state_manager = AgentStateManager(
        store, low_confidence_threshold=low_confidence_threshold
    )
    planner = Planner(readiness_threshold=readiness_threshold)
    trace_system = TraceSystem(store)
    executor = Executor(
        state_manager=state_manager,
        trace_system=trace_system,
        conflict_detection=ConflictDetectionService(store),
        medication_reconciliation=MedicationReconciliationService(store),
        pending_results=PendingResultsService(store),
        summary_generation=SummaryGenerationService(store),
    )
    return AgentLoop(
        storage=store,
        state_manager=state_manager,
        planner=planner,
        executor=executor,
        summary_generation=SummaryGenerationService(store),
        max_iterations=max_iterations,
    )
