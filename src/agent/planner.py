"""
Planner — Phase 10: deterministic next-action and readiness policy.

Architecture reference:
  architecture.md §3.8:
    'The agent loop is a bounded planner–executor cycle ... The loop
    terminates when summary_ready becomes true (driven by completion_score)
    or when max_iterations_reached is reached.'

  requirements.md FR-26:
    'The planner shall determine readiness from completion_score (a graded
    numeric signal), not from a single boolean.'

  requirements.md FR-33, FR-33b:
    Bounded termination; no infinite-loop plans.

  implementation_plan.md Phase 10:
    'Given an AgentState, the planner produces the next action.'

Planner-owned policy (not specified in architecture documents):
  - completion_score reflects pipeline goal progress and obstacle signals
    already exposed on AgentState (FR-25).
  - summary_ready when all standard pipeline goals are completed and
    evidence_count > 0.
  - Tool selection follows a fixed goal order for determinism and auditability.

The Planner does NOT execute tools or mutate AgentState.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.schemas.agent_state import AgentState

GOAL_DETECT_CONFLICTS = "detect_conflicts"
GOAL_RECONCILE_MEDICATIONS = "reconcile_medications"
GOAL_DETECT_PENDING_RESULTS = "detect_pending_results"
GOAL_GENERATE_SUMMARY = "generate_summary"

STANDARD_PIPELINE_GOALS: tuple[str, ...] = (
    GOAL_DETECT_CONFLICTS,
    GOAL_RECONCILE_MEDICATIONS,
    GOAL_DETECT_PENDING_RESULTS,
    GOAL_GENERATE_SUMMARY,
)


class AgentToolName(str, Enum):
    """Declared agent-loop tools implemented in Phases 7–8 and 13."""

    CONFLICT_DETECTION = "ConflictDetectionTool"
    MEDICATION_RECONCILIATION = "MedicationReconciliationTool"
    PENDING_RESULTS = "PendingResultsTool"
    SUMMARY_GENERATION = "SummaryGenerator"
    IDLE = "Idle"


_GOAL_TO_TOOL: dict[str, AgentToolName] = {
    GOAL_DETECT_CONFLICTS: AgentToolName.CONFLICT_DETECTION,
    GOAL_RECONCILE_MEDICATIONS: AgentToolName.MEDICATION_RECONCILIATION,
    GOAL_DETECT_PENDING_RESULTS: AgentToolName.PENDING_RESULTS,
    GOAL_GENERATE_SUMMARY: AgentToolName.SUMMARY_GENERATION,
}


@dataclass(frozen=True)
class PlannerDecision:
    """
    Planner output for one agent-loop iteration.

    Inter-component contract: consumed by Executor (Phase 11) only.
    Fields align with TraceStep requirements (goal, selected_tool, decision).
    """

    selected_tool: AgentToolName
    goal: str
    completion_score: float
    summary_ready: bool
    decision: str


class Planner:
    """
    Deterministic planner for the bounded agent loop.

    Consumer: AgentLoop / Executor (Phases 11–12).
    """

    def __init__(self, readiness_threshold: float = 0.85) -> None:
        if not (0.0 <= readiness_threshold <= 1.0):
            raise ValueError(
                "readiness_threshold must be in [0.0, 1.0]; "
                f"got {readiness_threshold!r}"
            )
        self._readiness_threshold = readiness_threshold

    def plan(self, state: AgentState) -> PlannerDecision:
        """
        Produce the next tool action and readiness signals for one iteration.

        Parameters
        ----------
        state:
            Current AgentState snapshot.  Not modified.

        Returns
        -------
        PlannerDecision
        """
        score = self._compute_completion_score(state)
        goals_complete = all(
            goal in state.completed_goals for goal in STANDARD_PIPELINE_GOALS
        )
        # Pipeline completion gates summary generation.  completion_score
        # remains a graded signal (FR-26); conflicts are surfaced, not
        # silently resolved (architecture.md §5.4).
        summary_ready = goals_complete and state.evidence_count > 0

        if summary_ready:
            return PlannerDecision(
                selected_tool=AgentToolName.SUMMARY_GENERATION,
                goal=GOAL_GENERATE_SUMMARY,
                completion_score=score,
                summary_ready=True,
                decision="pipeline complete; advance to summary generation",
            )

        next_goal = self._next_incomplete_goal(state)
        if next_goal is None:
            return PlannerDecision(
                selected_tool=AgentToolName.IDLE,
                goal=state.current_goal or "",
                completion_score=score,
                summary_ready=False,
                decision="no incomplete goals; awaiting readiness threshold",
            )

        tool = _GOAL_TO_TOOL[next_goal]
        return PlannerDecision(
            selected_tool=tool,
            goal=next_goal,
            completion_score=score,
            summary_ready=False,
            decision=f"execute {tool.value} for goal {next_goal}",
        )

    @staticmethod
    def _next_incomplete_goal(state: AgentState) -> str | None:
        for goal in STANDARD_PIPELINE_GOALS:
            if goal not in state.completed_goals:
                return goal
        return None

    @staticmethod
    def _compute_completion_score(state: AgentState) -> float:
        """
        Graded readiness signal (FR-26) from AgentState fields (FR-25).

        Returns a value in [0.0, 1.0].
        """
        if state.evidence_count == 0:
            return 0.0

        total_goals = len(STANDARD_PIPELINE_GOALS)
        completed = sum(
            1 for goal in STANDARD_PIPELINE_GOALS if goal in state.completed_goals
        )
        progress = completed / total_goals

        obstacle_penalty = min(
            0.4,
            0.08 * len(state.conflicts) + 0.04 * len(state.low_confidence_pages),
        )
        raw = 0.25 + 0.75 * progress - obstacle_penalty
        return max(0.0, min(1.0, raw))
