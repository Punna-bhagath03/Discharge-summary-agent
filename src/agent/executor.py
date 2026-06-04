"""
Executor — Phase 11: tool execution and AgentState transitions.

Architecture reference:
  requirements.md FR-33c, FR-33d:
    Executor increments iteration; no other component mutates iteration.

  implementation_plan.md Phase 11:
    'invoking the corresponding tool, applies the resulting changes to
    AgentState through declared transitions, and hands every step to the
    trace system.'

The Executor is the only component permitted to call AgentStateManager
mutating methods during the agent loop.
"""

from __future__ import annotations

import logging

from src.agent.planner import (
    GOAL_DETECT_CONFLICTS,
    GOAL_DETECT_PENDING_RESULTS,
    GOAL_GENERATE_SUMMARY,
    GOAL_RECONCILE_MEDICATIONS,
    AgentToolName,
    PlannerDecision,
)
from src.agent.state_manager import AgentStateManager
from src.agent.trace_system import TraceSystem
from src.schemas.agent_state import AgentState
from src.schemas.discharge_summary import DischargeSummary
from src.schemas.enums import TraceStatus
from src.services.conflict_detection_service import ConflictDetectionService
from src.services.medication_reconciliation_service import (
    MedicationReconciliationService,
)
from src.services.pending_results_service import PendingResultsService
from src.services.summary_generation_service import SummaryGenerationService

logger = logging.getLogger(__name__)


class Executor:
    """
    Executes Planner decisions and updates AgentState.

    Consumer: AgentLoop.
    """

    def __init__(
        self,
        state_manager: AgentStateManager,
        trace_system: TraceSystem,
        conflict_detection: ConflictDetectionService,
        medication_reconciliation: MedicationReconciliationService,
        pending_results: PendingResultsService,
        summary_generation: SummaryGenerationService,
    ) -> None:
        self._state_manager = state_manager
        self._trace = trace_system
        self._conflict_detection = conflict_detection
        self._medication_reconciliation = medication_reconciliation
        self._pending_results = pending_results
        self._summary_generation = summary_generation
        self._last_summary: DischargeSummary | None = None

    @property
    def last_summary(self) -> DischargeSummary | None:
        """DischargeSummary produced by the most recent summary tool run."""
        return self._last_summary

    def execute(
        self, state: AgentState, decision: PlannerDecision
    ) -> AgentState:
        """
        Run the selected tool and apply AgentState transitions.

        Parameters
        ----------
        state:
            AgentState before tool execution (current_goal and readiness
            fields already applied by AgentLoop).
        decision:
            Planner decision for this iteration.

        Returns
        -------
        AgentState
            Updated AgentState before iteration increment.
        """
        tool = decision.selected_tool
        status = TraceStatus.SUCCESS
        output_summary: dict[str, int | str | bool] = {
            "tool": tool.value,
            "success": True,
        }

        try:
            if tool == AgentToolName.CONFLICT_DETECTION:
                conflicts, flags = self._conflict_detection.detect_for_patient(
                    state.patient_id
                )
                state = self._state_manager.refresh_conflicts(state)
                state = self._state_manager.refresh_review_flags(state)
                state = self._state_manager.refresh_evidence_count(state)
                state = self._complete_goal(state, GOAL_DETECT_CONFLICTS)
                output_summary["conflicts_emitted"] = len(conflicts)
                output_summary["review_flags_emitted"] = len(flags)

            elif tool == AgentToolName.MEDICATION_RECONCILIATION:
                reconciled = self._medication_reconciliation.reconcile_for_patient(
                    state.patient_id
                )
                state = self._complete_goal(state, GOAL_RECONCILE_MEDICATIONS)
                output_summary["medication_records_returned"] = len(reconciled)

            elif tool == AgentToolName.PENDING_RESULTS:
                flags = self._pending_results.detect_for_patient(
                    state.patient_id
                )
                state = self._state_manager.refresh_review_flags(state)
                state = self._complete_goal(state, GOAL_DETECT_PENDING_RESULTS)
                output_summary["review_flags_emitted"] = len(flags)

            elif tool == AgentToolName.SUMMARY_GENERATION:
                self._last_summary = self._summary_generation.generate_for_patient(
                    state.patient_id
                )
                state = self._complete_goal(state, GOAL_GENERATE_SUMMARY)
                output_summary["summary_generated"] = True

            elif tool == AgentToolName.IDLE:
                output_summary["idle"] = True

            else:
                status = TraceStatus.FAILED
                output_summary["success"] = False
                output_summary["error"] = "unknown_tool"

        except Exception:
            logger.exception("executor: tool execution failed")
            status = TraceStatus.FAILED
            output_summary["success"] = False
            raise

        self._trace.record_tool_step(
            state,
            decision,
            status=status,
            tool_output_summary=output_summary,
        )
        return state

    def increment_iteration(
        self, state: AgentState, max_iterations: int
    ) -> AgentState:
        """
        Increment iteration exactly once (FR-33c) and record the transition.
        """
        new_state = self._state_manager.increment_iteration(
            state, max_iterations
        )
        self._trace.record_state_transition(
            new_state,
            decision="increment iteration",
            status=TraceStatus.SUCCESS,
        )
        return new_state

    def _complete_goal(self, state: AgentState, goal: str) -> AgentState:
        if state.current_goal != goal:
            state = self._state_manager.set_current_goal(state, goal)
        return self._state_manager.mark_current_goal_completed(state)
