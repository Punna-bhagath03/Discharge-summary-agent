"""
TraceStep schema — one recorded step in the agent's reasoning.

Architecture reference — architecture.md §4.7 and §5.6:
'Together these fields make the trace sufficient to fully reconstruct and
audit the agent's behavior.'

SR-19 mandates: trace_id, patient_id, iteration, goal, selected_tool,
tool_input, tool_output, decision, status, timestamp.

Required validations:
  - iteration >= 0
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.schemas.enums import TraceStatus


class TraceStep(BaseModel):
    """
    An immutable record of a single planner decision, tool invocation,
    executor action, or state transition within the agent loop.

    The full sequence of TraceStep records for a patient run constitutes the
    Trace Output — a first-class system output sufficient to reconstruct
    every agent decision and every fact in the final DischargeSummary.

    Steps are grouped by iteration for replay and audit (FR-35, SR-20).
    The Trace System writes every step via save_trace(); no other component
    persists trace data.
    """

    trace_id: str = Field(
        ...,
        description=(
            "Unique identifier for this TraceStep.  Allows individual steps "
            "to be retrieved and correlated across a run."
        ),
    )
    patient_id: str = Field(
        ...,
        description=(
            "Reference to the Patient record this step belongs to.  Groups "
            "all trace steps for a patient run."
        ),
    )
    iteration: int = Field(
        ...,
        ge=0,
        description=(
            "Agent-loop iteration during which this step was recorded.  "
            "Enables replay and analysis of the run iteration by iteration "
            "(SR-20)."
        ),
    )
    goal: str = Field(
        ...,
        description=(
            "The active goal in AgentState.current_goal at the time this "
            "step was recorded.  Provides context for the Planner's decision."
        ),
    )
    selected_tool: str = Field(
        ...,
        description=(
            "Name of the tool the Planner selected for this step "
            "(e.g. 'ConflictDetectionTool', 'OCRRetryTool', "
            "'SummaryGenerator').  Captures the exact tool invoked."
        ),
    )
    tool_input: str = Field(
        ...,
        description=(
            "Serialized representation of the data passed to selected_tool.  "
            "Stored as a string (e.g. JSON) so the exact input can be "
            "replayed without loss of fidelity."
        ),
    )
    tool_output: str = Field(
        ...,
        description=(
            "Serialized representation of the data produced by selected_tool.  "
            "Stored as a string (e.g. JSON) so the exact output is preserved "
            "for audit."
        ),
    )
    decision: str = Field(
        ...,
        description=(
            "The Planner or Executor decision that led to or resulted from "
            "this step — for example, 'retry OCR on page 3' or "
            "'advance to summary generation'.  Human-readable for audit."
        ),
    )
    status: TraceStatus = Field(
        ...,
        description=(
            "Outcome of this step.  One of SUCCESS, FAILED, RETRY, SKIPPED.  "
            "Drives analysis of agent behavior and identification of failure "
            "modes in the trace."
        ),
    )
    timestamp: datetime = Field(
        ...,
        description=(
            "UTC timestamp when this step was recorded.  Supports "
            "chronological ordering and elapsed-time analysis across the run."
        ),
    )

    @field_validator("iteration")
    @classmethod
    def iteration_must_be_non_negative(cls, value: int) -> int:
        """Required validation: iteration >= 0."""
        if value < 0:
            raise ValueError("iteration must be >= 0")
        return value
