"""
ReviewFlag schema — a condition requiring human attention, grounded in Evidence.

Architecture reference — architecture.md §4.5:
'evidence_ids makes review flags structurally grounded in the Evidence
Store: a flag never floats free of the evidence it concerns.'

Required validations:
  - evidence_ids cannot be empty
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.schemas.enums import ReviewSeverity


class ReviewFlag(BaseModel):
    """
    A first-class output that surfaces a condition requiring human attention.

    ReviewFlag records are produced by the Evidence Validation Tool (for
    rejected-but-clinically-relevant Evidence), the Conflict Detection Tool,
    the Missing Data Tool, and the Pending Results Tool.  Every ReviewFlag
    must reference the underlying Evidence via evidence_ids — free-floating
    flags are not permitted by the architecture (§4.5, SR-15).

    ReviewFlag records are propagated into DischargeSummary.review_flags so
    that the final output always carries the active human-review workload.
    """

    flag_id: str = Field(
        ...,
        description="Unique identifier for this ReviewFlag.",
    )
    category: str = Field(
        ...,
        description=(
            "Category of issue this flag represents "
            "(e.g. 'missing_data', 'conflict', 'low_confidence', "
            "'pending_result').  Used for grouping and filtering."
        ),
    )
    severity: ReviewSeverity = Field(
        ...,
        description=(
            "Urgency level of this flag.  Drives prioritisation during "
            "human review.  One of: low, medium, high, critical."
        ),
    )
    message: str = Field(
        ...,
        description=(
            "Human-readable explanation of the issue that triggered this flag.  "
            "Must be specific enough to act on without consulting raw Evidence."
        ),
    )
    evidence_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Identifiers of the Evidence records this flag concerns.  "
            "Must not be empty — a ReviewFlag must always be grounded in "
            "at least one Evidence record (SR-15)."
        ),
    )
    related_page: int = Field(
        ...,
        ge=1,
        description=(
            "1-based page number of the page most directly associated with "
            "this flag, for quick navigation during review."
        ),
    )
    created_at: datetime = Field(
        ...,
        description=(
            "Timestamp when this ReviewFlag was emitted.  Supports ordering "
            "flags chronologically within an agent run."
        ),
    )
    status: str = Field(
        ...,
        description=(
            "Current resolution status of this flag "
            "(e.g. 'open', 'resolved', 'acknowledged').  Managed by the "
            "Review Flag Tool and downstream review workflows."
        ),
    )

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_not_be_empty(cls, value: list[str]) -> list[str]:
        """
        Required validation: evidence_ids cannot be empty.

        Architecture SR-15: 'ReviewFlag records shall always reference the
        underlying Evidence via evidence_ids.  Free-floating review flags
        are not permitted.'
        """
        if not value:
            raise ValueError(
                "evidence_ids cannot be empty: every ReviewFlag must reference "
                "at least one Evidence record"
            )
        return value
