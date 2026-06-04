"""
AgentLoop — bounded planner–executor cycle (Phases 10–12 integration).

Architecture reference:
  architecture.md §3.8, §5.8:
    Terminates when summary_ready or max_iterations_reached.

  requirements.md FR-33, FR-33a–FR-33d.

  implementation_plan.md Phases 10–12.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agent.executor import Executor
from src.agent.planner import STANDARD_PIPELINE_GOALS, Planner
from src.agent.state_manager import AgentStateManager
from src.schemas.agent_state import AgentState
from src.schemas.discharge_summary import DischargeSummary
from src.schemas.trace_step import TraceStep
from src.services.summary_generation_service import SummaryGenerationService
from src.storage.storage_service import StorageService


@dataclass(frozen=True)
class AgentRunResult:
    """
    Outcome of a complete agent loop run.

    Inter-component contract for system output assembly (FR-41–FR-43).
    """

    final_state: AgentState
    discharge_summary: DischargeSummary | None
    trace: list[TraceStep]


class AgentLoop:
    """
    Bounded agent loop wiring Planner, Executor, and TraceSystem.

    Consumer: application entry points / integration tests.
    """

    def __init__(
        self,
        storage: StorageService,
        state_manager: AgentStateManager,
        planner: Planner,
        executor: Executor,
        summary_generation: SummaryGenerationService,
        *,
        max_iterations: int = 10,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        self._storage = storage
        self._state_manager = state_manager
        self._planner = planner
        self._executor = executor
        self._summary_generation = summary_generation
        self._max_iterations = max_iterations

    def run(self, patient_id: str) -> AgentRunResult:
        """
        Execute the agent loop for a patient until termination.

        Termination (FR-33): summary_ready or max_iterations_reached.
        """
        state = self._state_manager.initialize_state(patient_id)
        if not state.pending_goals:
            state = self._state_manager.set_pending_goals(
                state, list(STANDARD_PIPELINE_GOALS)
            )

        while not (state.summary_ready or state.max_iterations_reached):
            decision = self._planner.plan(state)
            state = self._state_manager.set_current_goal(state, decision.goal)
            state = self._state_manager.set_completion_score(
                state, decision.completion_score
            )
            state = self._state_manager.set_summary_ready(
                state, decision.summary_ready
            )
            state = self._executor.execute(state, decision)
            state = self._executor.increment_iteration(
                state, self._max_iterations
            )

        summary = self._executor.last_summary
        if summary is None and state.summary_ready:
            summary = self._summary_generation.generate_for_patient(patient_id)

        trace = self._storage.get_trace_for_patient(patient_id)
        return AgentRunResult(
            final_state=state,
            discharge_summary=summary,
            trace=trace,
        )
