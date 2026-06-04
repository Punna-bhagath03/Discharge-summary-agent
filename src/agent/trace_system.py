"""
TraceSystem — Phase 12: append-only TraceStep recording.

Architecture reference:
  architecture.md §3.11, §5.6:
    'Every planner decision, every tool invocation, every state transition,
    and every produced artifact is recorded as a TraceStep.'

  requirements.md FR-34, FR-34a, FR-35, FR-36.

  implementation_plan.md Phase 12:
    'recorded as a TraceStep via save_trace().'

The Trace System is the only permitted caller of save_trace().

NFR-9: tool_input and tool_output use aggregate JSON without clinical
field values or source text.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from src.agent.planner import PlannerDecision
from src.schemas.agent_state import AgentState
from src.schemas.enums import TraceStatus
from src.schemas.trace_step import TraceStep
from src.storage.storage_service import StorageService

logger = logging.getLogger(__name__)


class TraceSystem:
    """
    Append-only trace recorder for the agent loop.

    Consumer: Executor (Phase 11).
    """

    def __init__(self, storage: StorageService) -> None:
        self._storage = storage

    def record_tool_step(
        self,
        state: AgentState,
        decision: PlannerDecision,
        *,
        status: TraceStatus,
        tool_output_summary: dict[str, int | str | bool],
    ) -> TraceStep:
        """
        Persist one TraceStep for a tool invocation.

        Parameters
        ----------
        state:
            AgentState after the tool step (iteration not yet incremented).
        decision:
            Planner decision that selected the tool.
        status:
            Step outcome (FR-36).
        tool_output_summary:
            PHI-free summary counts for tool_output serialization.

        Returns
        -------
        TraceStep
            The persisted trace step.
        """
        tool_input = json.dumps({"patient_id": state.patient_id})
        tool_output = json.dumps(tool_output_summary)

        step = TraceStep(
            trace_id=str(uuid.uuid4()),
            patient_id=state.patient_id,
            iteration=state.iteration,
            goal=decision.goal,
            selected_tool=decision.selected_tool.value,
            tool_input=tool_input,
            tool_output=tool_output,
            decision=decision.decision,
            status=status,
            timestamp=datetime.now(timezone.utc),
        )
        self._storage.save_trace(step)
        logger.debug(
            "trace: recorded step tool=%s status=%s iteration=%d",
            decision.selected_tool.value,
            status.value,
            state.iteration,
        )
        return step

    def record_state_transition(
        self,
        state: AgentState,
        *,
        decision: str,
        status: TraceStatus = TraceStatus.SUCCESS,
    ) -> TraceStep:
        """
        Record a state-only transition (for example iteration increment).
        """
        step = TraceStep(
            trace_id=str(uuid.uuid4()),
            patient_id=state.patient_id,
            iteration=state.iteration,
            goal=state.current_goal,
            selected_tool="AgentStateManager",
            tool_input=json.dumps({"patient_id": state.patient_id}),
            tool_output=json.dumps(
                {
                    "iteration": state.iteration,
                    "summary_ready": state.summary_ready,
                    "max_iterations_reached": state.max_iterations_reached,
                }
            ),
            decision=decision,
            status=status,
            timestamp=datetime.now(timezone.utc),
        )
        self._storage.save_trace(step)
        return step
