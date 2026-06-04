"""
EvidenceValidationTool — Phase 5: Evidence Validation (pure validation).

Architecture reference:
  architecture.md §3.5:
    'Evidence Validation is a first-class architectural component, not a
    processing afterthought. It is the gate that protects the Evidence
    Store from polluted data and is responsible for enforcing the
    no-hallucination invariant.'

  requirements.md FR-13 through FR-22.

  implementation_plan.md Phase 5:
    'Implement Evidence Validation as a first-class service and the gate
    to the Evidence Store.'

This module contains ONLY the per-record validation logic.  It is pure:
it has no storage dependency, performs no persistence, performs no
deduplication (which requires batch/store context and is owned by the
EvidenceValidationService), and emits no ReviewFlags, Conflicts,
TraceSteps, or AgentState mutations.

Architecture-gap notes (no behavior invented here):
  - FR-14 (invalid dates): the Evidence schema (architecture.md §4.3,
    requirements.md SR-7) defines no date-typed field.  Treating a
    field_value string as a date would require inventing date-field
    semantics, which is an undefined architecture gap.  No date parsing
    is performed; FR-14 has no applicable target on an Evidence record.
  - FR-15 (deduplication equivalence): requirements.md FR-15 requires
    deduplication but does not define what makes two Evidence records
    equivalent.  The service uses exact-span provenance
    (patient_id, document_name, page_number, source_start_char,
    source_end_char) as the equivalence key, which is the identity
    documented by StorageService.get_evidence_by_provenance
    (architecture.md §5.3).  No semantic, fuzzy, or field-level equality
    is applied.  This is an architecture gap; the equivalence rule is
    not defined and therefore cannot be invented.

NFR-9: this module logs nothing.  It returns enum reason codes only and
never handles or surfaces patient-linked values.
"""

from enum import Enum

from src.schemas.evidence import Evidence


class RejectionReason(str, Enum):
    """
    Internal, PHI-free reason codes for why an Evidence record was rejected.

    These are diagnostic codes used by the validation gate and its result
    type.  They are NOT a ReviewFlag taxonomy (category/severity/status),
    which the architecture leaves undefined and which this phase does not
    invent.  Each code maps 1:1 to a documented validation requirement.
    """

    MISSING_REQUIRED_FIELD = "missing_required_field"          # FR-13
    INVALID_CONFIDENCE = "invalid_confidence"                  # FR-16
    BROKEN_PROVENANCE = "broken_provenance"                    # FR-17
    SOURCE_START_CHAR_NEGATIVE = "source_start_char_negative"  # FR-18
    SOURCE_END_NOT_AFTER_START = "source_end_not_after_start"  # FR-19
    SOURCE_END_EXCEEDS_TEXT = "source_end_exceeds_text"        # FR-20
    EMPTY_REQUIRED_VALUE = "empty_required_value"              # FR-21
    DUPLICATE_EVIDENCE = "duplicate_evidence"                  # FR-15


# Fields that must be present (non-None) on every Evidence record (FR-13).
# Mirrors the required field set in architecture.md §4.3 / requirements.md SR-7.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "evidence_id",
    "patient_id",
    "evidence_type",
    "field_name",
    "field_value",
    "document_name",
    "page_number",
    "source_text",
    "source_start_char",
    "source_end_char",
    "section",
    "ocr_confidence",
    "extraction_confidence",
    "extraction_method",
    "status",
)

# Required string fields that must additionally be non-empty (FR-21).
# Includes every string field listed as required in architecture.md §4.3
# and requirements.md SR-7.  Numeric and enum fields are excluded because
# emptiness does not apply to them.
_REQUIRED_NON_EMPTY_STRING_FIELDS: tuple[str, ...] = (
    "evidence_id",
    "patient_id",
    "field_name",
    "field_value",
    "document_name",
    "section",
    "source_text",
    "extraction_method",
    "status",
)


class EvidenceValidationTool:
    """
    Pure per-record validation for the Phase 5 Evidence Validation gate.

    Consumer: EvidenceValidationService (src/services/).
    Citation:  architecture.md §3.5; requirements.md FR-13, FR-16 through
               FR-21; implementation_plan.md Phase 5.

    The tool enforces every per-record rule that does not require batch or
    storage context.  Deduplication (FR-15) is performed by the service
    because it requires comparison against other records and the Evidence
    Store.
    """

    def validate(self, evidence: Evidence) -> list[RejectionReason]:
        """
        Return the list of rejection reasons for a single Evidence record.

        An empty list means the record passed every per-record check and is
        eligible for admission (subject to the service's FR-15 dedup check).

        Consumer: EvidenceValidationService.validate_and_store().
        Citation:
            requirements.md FR-13:
                'reject records with missing required fields.'
            requirements.md FR-16:
                'reject records with invalid ocr_confidence or
                extraction_confidence values.'
            requirements.md FR-17:
                'reject records with broken provenance references.'
            requirements.md FR-18:
                'reject records where source_start_char < 0.'
            requirements.md FR-19:
                'reject records where source_end_char <= source_start_char.'
            requirements.md FR-20:
                'reject records where source_end_char exceeds the length of
                source_text.'
            requirements.md FR-21:
                'reject records with empty values where values are required.'

        Parameters
        ----------
        evidence:
            The Evidence record to validate.  Not modified.

        Returns
        -------
        list[RejectionReason]
            Zero or more PHI-free reason codes.  The list may contain
            multiple reasons when a record violates several rules.
        """
        reasons: list[RejectionReason] = []

        # FR-13 — missing required fields.
        missing = any(
            getattr(evidence, name, None) is None for name in _REQUIRED_FIELDS
        )
        if missing:
            reasons.append(RejectionReason.MISSING_REQUIRED_FIELD)

        # FR-21 — empty required string values.
        for name in _REQUIRED_NON_EMPTY_STRING_FIELDS:
            value = getattr(evidence, name, None)
            if isinstance(value, str) and not value.strip():
                reasons.append(RejectionReason.EMPTY_REQUIRED_VALUE)
                break

        # FR-16 — confidence values must be within [0.0, 1.0].
        if not self._confidence_in_range(
            evidence.ocr_confidence
        ) or not self._confidence_in_range(evidence.extraction_confidence):
            reasons.append(RejectionReason.INVALID_CONFIDENCE)

        # FR-17 — broken provenance references.
        if self._provenance_broken(evidence):
            reasons.append(RejectionReason.BROKEN_PROVENANCE)

        # FR-18 / FR-19 / FR-20 — provenance span integrity.
        reasons.extend(self._span_reasons(evidence))

        return reasons

    @staticmethod
    def _confidence_in_range(value: float | None) -> bool:
        """Return True when value is a number within [0.0, 1.0] (FR-16)."""
        if value is None:
            return False
        return 0.0 <= value <= 1.0

    @staticmethod
    def _provenance_broken(evidence: Evidence) -> bool:
        """
        Return True when any provenance reference is missing or structurally
        unusable (FR-17): document_name, page_number, source_text,
        source_start_char, or source_end_char.
        """
        if not isinstance(evidence.document_name, str) or not evidence.document_name.strip():
            return True
        if evidence.page_number is None or evidence.page_number < 1:
            return True
        if evidence.source_text is None:
            return True
        if evidence.source_start_char is None or evidence.source_end_char is None:
            return True
        return False

    @staticmethod
    def _span_reasons(evidence: Evidence) -> list[RejectionReason]:
        """
        Return span-integrity rejection reasons (FR-18, FR-19, FR-20).

        Guards against None so the gate never raises on a malformed record;
        missing values are reported as BROKEN_PROVENANCE by _provenance_broken
        and are skipped here.
        """
        start = evidence.source_start_char
        end = evidence.source_end_char
        text = evidence.source_text
        if start is None or end is None or text is None:
            return []

        span_reasons: list[RejectionReason] = []
        if start < 0:
            span_reasons.append(RejectionReason.SOURCE_START_CHAR_NEGATIVE)
        if end <= start:
            span_reasons.append(RejectionReason.SOURCE_END_NOT_AFTER_START)
        if end > len(text):
            span_reasons.append(RejectionReason.SOURCE_END_EXCEEDS_TEXT)
        return span_reasons
