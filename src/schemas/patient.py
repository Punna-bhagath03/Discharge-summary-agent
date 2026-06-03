"""
Patient schema — the first-class anchor for the entire discharge summary
agent system.

Architecture reference — architecture.md §4.1:
'Patient is the first-class anchor for the entire system.  All other
artifacts reference a patient via patient_id and are grouped by it.'
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Patient(BaseModel):
    """
    Represents a patient whose documents are being processed.

    Every other artifact in the system (Page, Evidence, Conflict, ReviewFlag,
    AgentState, TraceStep, DischargeSummary) references a Patient via
    patient_id.  Fields patient_name, age, and gender are optional because
    they may be unknown at ingestion time; they are never fabricated.
    """

    patient_id: str = Field(
        ...,
        description=(
            "Stable, unique identifier for this patient.  All other artifacts "
            "in the system reference a Patient through this field."
        ),
    )
    patient_name: str | None = Field(
        default=None,
        description=(
            "Full name of the patient.  None when unknown; never fabricated."
        ),
    )
    age: str | None = Field(
        default=None,
        description=(
            "Patient age, expressed as a string to accommodate representations "
            "such as '45', '6 months', or '2 years'.  None when unknown; "
            "never fabricated.  Numeric values must not be negative."
        ),
    )
    gender: str | None = Field(
        default=None,
        description=(
            "Patient gender.  None when unknown; never fabricated."
        ),
    )
    documents: list[str] = Field(
        ...,
        description=(
            "Names of documents ingested for this patient.  Each entry "
            "corresponds to a document_name used across Page and Evidence "
            "records."
        ),
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when this Patient record was first created.",
    )

    @field_validator("age")
    @classmethod
    def age_must_be_non_negative(cls, value: str | None) -> str | None:
        """
        Requirement — architecture validation rules:
        'age cannot be negative if present.'

        When age is a string that parses as a number, that number must not
        be negative.  Non-numeric strings (e.g. '6 months') are accepted
        as-is because the architecture uses str to accommodate varied formats.
        """
        if value is None:
            return value
        try:
            numeric = float(value)
        except ValueError:
            return value
        if numeric < 0:
            raise ValueError("age cannot be negative")
        return value
