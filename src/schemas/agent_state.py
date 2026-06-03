"""
AgentState schema — the working memory of the bounded agent loop.

Architecture reference — architecture.md §3.7 and §4.6:
'The Agent State is the working memory of the loop.  It is an explicit,
inspectable object that the planner and executor read from and write to.'

Required validations:
  - iteration >= 0
  - evidence_count >= 0
  - completion_score in [0.0, 1.0]

Architecture termination contract (§5.8):
  The executor is solely responsible for incrementing iteration.  The loop
  terminates only when summary_ready == True or
  max_iterations_reached == True.
"""

from pydantic import BaseModel, Field, field_validator

from src.schemas.conflict import Conflict


class AgentState(BaseModel):
    """
    Explicit, inspectable working memory for the agent loop.

    The Planner reads AgentState to decide the next action.  The Executor
    mutates AgentState (and is the only component permitted to do so) and
    records every transition as a TraceStep.

    completion_score is the primary readiness signal: the Planner uses it as
    a graded numeric signal rather than a simple boolean to decide when the
    Evidence Store contains enough validated facts to generate the summary.

    low_confidence_pages is read directly by the OCR Retry Tool so that it
    can re-process only the pages that need attention, without rescanning
    the full document set.
    """

    patient_id: str = Field(
        ...,
        description=(
            "Reference to the Patient record this agent run is processing.  "
            "All artifacts produced during the run are associated with this "
            "patient_id."
        ),
    )
    iteration: int = Field(
        ...,
        ge=0,
        description=(
            "Current iteration count of the agent loop.  Incremented by "
            "exactly one per iteration, exclusively by the Executor.  "
            "Used by the Executor to derive max_iterations_reached against "
            "the configurable MAX_AGENT_ITERATIONS limit."
        ),
    )
    current_goal: str = Field(
        ...,
        description=(
            "The goal the Planner is currently working toward.  Recorded in "
            "every TraceStep emitted during this iteration."
        ),
    )
    completed_goals: list[str] = Field(
        default_factory=list,
        description="Goals that have been fully achieved in previous iterations.",
    )
    pending_goals: list[str] = Field(
        default_factory=list,
        description=(
            "Goals that have been identified but not yet actioned.  The "
            "Planner selects from this list when choosing the next action."
        ),
    )
    conflicts: list[Conflict] = Field(
        default_factory=list,
        description=(
            "Self-contained Conflict records detected during this run.  "
            "The Planner uses this list to decide whether to invoke the "
            "Conflict Detection or Medication Reconciliation tools."
        ),
    )
    review_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Identifiers of ReviewFlag records raised during this run.  "
            "Stored as IDs (not embedded objects) to keep AgentState lean; "
            "the full ReviewFlag objects are held by the Review Flag store."
        ),
    )
    low_confidence_pages: list[int] = Field(
        default_factory=list,
        description=(
            "1-based page numbers whose ocr_confidence fell below the "
            "configured threshold.  The OCR Retry Tool reads this field "
            "directly and re-OCRs only the listed pages."
        ),
    )
    evidence_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of validated Evidence records in the Evidence Store for "
            "this patient at the time this state was last updated.  Used as "
            "an input to completion_score."
        ),
    )
    completion_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Graded readiness signal in [0.0, 1.0] computed from the current "
            "state.  The Planner evaluates this against a threshold to decide "
            "whether to proceed to summary generation.  A simple boolean is "
            "explicitly insufficient per FR-26."
        ),
    )
    summary_ready: bool = Field(
        ...,
        description=(
            "Set to True by the Planner when completion_score meets the "
            "readiness threshold.  One of the two permitted loop-termination "
            "conditions (§5.8)."
        ),
    )
    max_iterations_reached: bool = Field(
        ...,
        description=(
            "Set to True by the Executor when iteration reaches "
            "MAX_AGENT_ITERATIONS.  The other permitted loop-termination "
            "condition (§5.8).  The loop terminates if either this or "
            "summary_ready is True."
        ),
    )

    @field_validator("iteration")
    @classmethod
    def iteration_must_be_non_negative(cls, value: int) -> int:
        """Required validation: iteration >= 0."""
        if value < 0:
            raise ValueError("iteration must be >= 0")
        return value

    @field_validator("evidence_count")
    @classmethod
    def evidence_count_must_be_non_negative(cls, value: int) -> int:
        """Required validation: evidence_count >= 0."""
        if value < 0:
            raise ValueError("evidence_count must be >= 0")
        return value

    @field_validator("completion_score")
    @classmethod
    def completion_score_must_be_in_range(cls, value: float) -> float:
        """Required validation: completion_score in [0.0, 1.0]."""
        if not (0.0 <= value <= 1.0):
            raise ValueError("completion_score must be between 0.0 and 1.0")
        return value
