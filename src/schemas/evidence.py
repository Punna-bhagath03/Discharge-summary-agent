"""
Evidence schema — a single extracted, provenance-bearing clinical fact.

Architecture reference — architecture.md §4.3 and §5.3:
'The four provenance fields — document_name, page_number, source_text, and
the (source_start_char, source_end_char) pair — together guarantee that
every fact can be traced back to the exact originating text span on a
specific page of a specific document.'

Required validations (architecture.md §5.3, requirements.md §8):
  - source_start_char >= 0
  - source_end_char > source_start_char
  - source_end_char <= len(source_text)
  - ocr_confidence in [0.0, 1.0]
  - extraction_confidence in [0.0, 1.0]
  - field_value is not empty or whitespace-only
"""

from pydantic import BaseModel, Field, field_validator, model_validator

from src.schemas.enums import EvidenceType


class Evidence(BaseModel):
    """
    A single structured fact extracted from a Page, bearing full exact-span
    provenance.

    Every Evidence record must reference the exact character range within
    source_text from which it was extracted.  This is enforced by validators
    and is the foundation of the system's no-hallucination guarantee.

    The triple (document_name, page_number, source_text + char span) allows
    any downstream consumer — including the Summary Generator and human
    reviewers — to locate the original passage that produced the fact.
    """

    evidence_id: str = Field(
        ...,
        description="Unique identifier for this Evidence record.",
    )
    evidence_type: EvidenceType = Field(
        ...,
        description=(
            "Clinical or administrative class of this fact.  Drives "
            "reconciliation and conflict detection logic in later phases.  "
            "Example: EvidenceType.MEDICATION."
        ),
    )
    field_name: str = Field(
        ...,
        description=(
            "Name of the specific field being extracted within its "
            "evidence_type category.  "
            "Example: 'medication_name', 'diagnosis_code', 'allergy_substance'."
        ),
    )
    field_value: str = Field(
        ...,
        description=(
            "Extracted value for field_name.  "
            "Example: field_name='medication_name', field_value='metformin'."
        ),
    )
    document_name: str = Field(
        ...,
        description=(
            "Name of the source document from which this fact was extracted.  "
            "Provenance key; carried forward from the originating Page record."
        ),
    )
    page_number: int = Field(
        ...,
        ge=1,
        description=(
            "1-based page number within document_name from which this fact "
            "was extracted.  Provenance key; carried forward from the "
            "originating Page record."
        ),
    )
    source_text: str = Field(
        ...,
        description=(
            "The OCR-recognized text of the page region from which this fact "
            "was extracted.  source_start_char and source_end_char index into "
            "this string.  Quoting source_text enables exact-span verification."
        ),
    )
    source_start_char: int = Field(
        ...,
        ge=0,
        description=(
            "Inclusive start index of the extracted span within source_text.  "
            "Must be >= 0.  Together with source_end_char this pins the fact "
            "to a precise location in the OCR output."
        ),
    )
    source_end_char: int = Field(
        ...,
        description=(
            "Exclusive end index of the extracted span within source_text.  "
            "Must be > source_start_char and <= len(source_text)."
        ),
    )
    section: str = Field(
        ...,
        description=(
            "Document section from which the fact was extracted "
            "(e.g. 'Medications', 'Discharge Diagnosis', 'Allergies').  "
            "An empty string is acceptable when no section can be determined."
        ),
    )
    ocr_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in the OCR text recognition for the source span, "
            "in [0.0, 1.0].  Inherited from the originating Page record.  "
            "Distinct from extraction_confidence."
        ),
    )
    extraction_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence that field_value was correctly structured from "
            "source_text, in [0.0, 1.0].  Distinct from ocr_confidence; "
            "these two signals must not be collapsed into one."
        ),
    )
    extraction_method: str = Field(
        ...,
        description=(
            "Method or model used to extract this fact from source_text "
            "(e.g. 'regex', 'llm', 'rule-based').  Supports auditability."
        ),
    )
    status: str = Field(
        ...,
        description=(
            "Lifecycle status of this Evidence record as managed by the "
            "Evidence Validation Tool (e.g. 'pending', 'validated', "
            "'rejected')."
        ),
    )

    @field_validator("source_start_char")
    @classmethod
    def start_char_must_be_non_negative(cls, value: int) -> int:
        """
        Architecture §5.3 / requirements FR-18:
        'source_start_char >= 0'

        Note: the Field(ge=0) constraint already enforces this at the
        Pydantic layer.  This explicit validator ensures the rule is
        discoverable and produces a clear error message.
        """
        if value < 0:
            raise ValueError("source_start_char must be >= 0")
        return value

    @field_validator("field_value")
    @classmethod
    def field_value_must_not_be_blank(cls, value: str) -> str:
        """Required value-bearing evidence must not be empty or whitespace-only."""
        if not value.strip():
            raise ValueError("field_value must not be empty or whitespace-only")
        return value

    @model_validator(mode="after")
    def validate_char_span_integrity(self) -> "Evidence":
        """
        Architecture §5.3 / requirements FR-19, FR-20:
        - 'source_end_char > source_start_char'
        - 'source_end_char <= len(source_text)'

        These are cross-field constraints and therefore require a
        model_validator rather than individual field_validators.
        """
        if self.source_end_char <= self.source_start_char:
            raise ValueError(
                "source_end_char must be greater than source_start_char "
                f"(got source_start_char={self.source_start_char}, "
                f"source_end_char={self.source_end_char})"
            )
        if self.source_end_char > len(self.source_text):
            raise ValueError(
                "source_end_char must not exceed len(source_text) "
                f"(source_end_char={self.source_end_char}, "
                f"len(source_text)={len(self.source_text)})"
            )
        return self
