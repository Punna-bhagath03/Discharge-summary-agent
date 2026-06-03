"""
DischargeSummary schema — the final structured output of the agent pipeline.

Architecture reference — architecture.md §4.8:
'diagnoses, medications, allergies, procedures, pending_results, and
follow_up_instructions are lists of structured entries.  review_flags is a
list of review flag identifiers.  Every entry in any of these clinical lists
must be traceable to one or more entries in supporting_evidence_ids, each of
which resolves to an Evidence record carrying exact-span provenance.'

The architecture mandates typed, structured clinical entries — not free-form
text and not Dict[str, Any].  SummaryEntry mirrors the Evidence
(field_name / field_value) model and carries its own supporting evidence IDs
so every summary entry is individually traceable.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class SummaryEntry(BaseModel):
    """
    A single structured item within a clinical section of the DischargeSummary.

    The architecture requires structured (not free-form) entries for
    diagnoses, medications, allergies, procedures, pending_results, and
    follow_up_instructions (SR-23).  Every entry must be traceable to one or
    more Evidence records via DischargeSummary.supporting_evidence_ids (SR-24).

    field_name and field_value mirror the Evidence extraction model.
    supporting_evidence_ids makes each individual entry traceable to one or
    more Evidence records.
    """

    field_name: str = Field(
        ...,
        description=(
            "Name of the clinical field represented by this entry.  "
            "Mirrors the field_name on the originating Evidence record "
            "(e.g. 'diagnosis_name', 'medication_name', 'allergy_substance', "
            "'procedure_description', 'follow_up_instruction')."
        ),
    )
    field_value: str = Field(
        ...,
        description=(
            "Value of the clinical field represented by this entry.  "
            "Derived strictly from validated Evidence in the Evidence Store; "
            "never fabricated."
        ),
    )
    supporting_evidence_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Identifiers of Evidence records that support this specific "
            "summary entry.  Must contain at least one evidence_id so every "
            "entry is individually traceable."
        ),
    )

    @field_validator("supporting_evidence_ids")
    @classmethod
    def supporting_evidence_ids_must_not_be_empty(
        cls, value: list[str]
    ) -> list[str]:
        """Every SummaryEntry must be individually evidence-grounded."""
        if not value:
            raise ValueError(
                "supporting_evidence_ids cannot be empty for a SummaryEntry"
            )
        return value


class DischargeSummary(BaseModel):
    """
    The final structured output produced by the Summary Generator.

    DischargeSummary is a first-class schema — not free-form text.  It is
    composed strictly from validated Evidence records and active ReviewFlag
    identifiers.  No content is introduced from outside the Evidence Store.

    Every entry in the clinical lists (diagnoses, medications, allergies,
    procedures, pending_results, follow_up_instructions) must be traceable
    through supporting_evidence_ids to one or more Evidence records, each of
    which carries its own exact-span provenance — fulfilling the end-to-end
    auditability requirement (acceptance criteria §8, architecture §7).
    """

    patient_id: str = Field(
        ...,
        description=(
            "Reference to the Patient record this summary was generated for.  "
            "All clinical entries in this summary are derived from Evidence "
            "records associated with this patient_id."
        ),
    )
    diagnoses: list[SummaryEntry] = Field(
        default_factory=list,
        description=(
            "Structured list of diagnosis entries derived from Evidence records "
            "with evidence_type=DIAGNOSIS.  Each entry is traceable to one or "
            "more supporting_evidence_ids."
        ),
    )
    medications: list[SummaryEntry] = Field(
        default_factory=list,
        description=(
            "Structured list of medication entries derived from Evidence records "
            "with evidence_type=MEDICATION.  Each entry is traceable to one or "
            "more supporting_evidence_ids."
        ),
    )
    allergies: list[SummaryEntry] = Field(
        default_factory=list,
        description=(
            "Structured list of allergy entries derived from Evidence records "
            "with evidence_type=ALLERGY.  Each entry is traceable to one or "
            "more supporting_evidence_ids."
        ),
    )
    procedures: list[SummaryEntry] = Field(
        default_factory=list,
        description=(
            "Structured list of procedure entries.  Each entry is traceable "
            "to one or more supporting_evidence_ids."
        ),
    )
    pending_results: list[SummaryEntry] = Field(
        default_factory=list,
        description=(
            "Structured list of clinical results marked as pending in the "
            "source documents.  Derived from Evidence records with "
            "evidence_type=PENDING_RESULT.  Each entry is traceable to one "
            "or more supporting_evidence_ids."
        ),
    )
    follow_up_instructions: list[SummaryEntry] = Field(
        default_factory=list,
        description=(
            "Structured list of follow-up instructions for the patient.  "
            "Derived from Evidence records with evidence_type=FOLLOW_UP.  "
            "Each entry is traceable to one or more supporting_evidence_ids."
        ),
    )
    review_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Identifiers of ReviewFlag records that were active at the time "
            "of summary generation.  Propagated from AgentState.review_flags "
            "so that human reviewers can see the full review workload alongside "
            "the clinical content."
        ),
    )
    supporting_evidence_ids: list[str] = Field(
        ...,
        description=(
            "Complete set of Evidence record identifiers that support the "
            "clinical content of this summary.  Every entry in diagnoses, "
            "medications, allergies, procedures, pending_results, and "
            "follow_up_instructions must resolve to one or more entries in "
            "this list (SR-24).  Enables end-to-end auditability: "
            "DischargeSummary → supporting_evidence_ids → Evidence → "
            "source_text → source character span → originating page."
        ),
    )
    generated_at: datetime = Field(
        ...,
        description=(
            "UTC timestamp when this DischargeSummary was produced by the "
            "Summary Generator."
        ),
    )

    @model_validator(mode="after")
    def clinical_entries_must_have_supporting_evidence(
        self,
    ) -> "DischargeSummary":
        """Clinical entries must never exist without supporting evidence."""
        clinical_sections = (
            self.diagnoses,
            self.medications,
            self.allergies,
            self.procedures,
            self.pending_results,
            self.follow_up_instructions,
        )
        for section in clinical_sections:
            for entry in section:
                if not entry.supporting_evidence_ids:
                    raise ValueError(
                        "every SummaryEntry must include at least one "
                        "supporting_evidence_id"
                    )
        return self
