"""
Conflict schema — a detected disagreement between two or more Evidence records.

Architecture reference — architecture.md §4.4:
'Conflict objects must be self-contained and auditable without requiring a
re-query of the Evidence Store to understand the disputed field, disputed
values, or supporting evidence.'

Required validations:
  - evidence_ids cannot be empty
  - conflicting_values cannot be empty
"""

from pydantic import BaseModel, Field, field_validator


class Conflict(BaseModel):
    """
    A self-contained record of a detected disagreement between evidence items.

    The Conflict Detection Tool produces these records when two or more
    Evidence entries for the same field carry different values.  Conflicts
    are never silently resolved; they are surfaced as ReviewFlag records and
    stored in AgentState.conflicts for the planner to act on.

    All information required to understand the conflict is embedded in this
    object — downstream consumers must not need to re-query the Evidence
    Store.
    """

    field_name: str = Field(
        ...,
        description=(
            "The field on which the conflict was detected.  Matches the "
            "field_name used on the conflicting Evidence records "
            "(e.g. 'medication_dose', 'diagnosis_code')."
        ),
    )
    conflicting_values: list[str] = Field(
        ...,
        min_length=2,
        description=(
            "The set of disagreeing values found across the evidence records "
            "for field_name.  Must contain at least two entries — a single "
            "value cannot constitute a conflict.  Ordered by evidence discovery."
        ),
    )
    evidence_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Identifiers of the Evidence records whose values disagree.  "
            "Must not be empty.  Each entry corresponds to an evidence_id "
            "in the Evidence Store, making this Conflict self-contained "
            "and auditable."
        ),
    )

    @field_validator("conflicting_values")
    @classmethod
    def conflicting_values_must_not_be_empty(
        cls, value: list[str]
    ) -> list[str]:
        """
        Required validation: conflicting_values cannot be empty.

        The min_length=2 Field constraint enforces this at the Pydantic layer.
        This explicit validator produces a clear domain error message.
        """
        if not value:
            raise ValueError("conflicting_values cannot be empty")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_not_be_empty(cls, value: list[str]) -> list[str]:
        """
        Required validation: evidence_ids cannot be empty.

        A Conflict without supporting Evidence IDs cannot be audited.
        """
        if not value:
            raise ValueError("evidence_ids cannot be empty")
        return value
