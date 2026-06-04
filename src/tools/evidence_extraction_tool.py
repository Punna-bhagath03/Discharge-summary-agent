"""
EvidenceExtractionTool — Phase 4: Evidence Extraction.

Architecture reference:
  architecture.md §3.4:
    'Reads pages from the Page Store and emits structured Evidence records.
    Every record carries the exact span (source_start_char, source_end_char)
    within source_text on a specific (document_name, page_number).
    Extraction never produces an evidence record without a complete
    provenance triplet.'

  architecture.md §6:
    'src/tools/ — OCR Tool, Evidence Extraction Tool, Evidence Validation
    Tool, plus the agent-loop tools.'

  requirements.md FR-9 through FR-12.

  implementation_plan.md Phase 4:
    'Implement the Evidence Extraction Tool. It reads pages from the Page
    Store and emits Evidence records, each carrying a complete exact-span
    provenance triplet (document_name, page_number, source_text,
    source_start_char, source_end_char).'

Phase 4 boundary — this module ONLY:
  - Reads Page.raw_text.
  - Applies rule-based patterns.
  - Constructs Evidence records in memory.
  - Returns Evidence records to the caller.

It does NOT:
  - Call save_evidence() (owned by Phase 5 via Evidence Validation).
  - Validate Evidence (owned by Phase 5).
  - Deduplicate Evidence (owned by Phase 5, FR-15).
  - Create ReviewFlags (owned by Phase 5 and later tool phases).
  - Mutate AgentState (owned by Phases 9/11).
  - Emit TraceSteps (owned by Phase 12).
"""

import logging
import re
import uuid
from dataclasses import dataclass

from pydantic import ValidationError

from src.schemas.enums import EvidenceType
from src.schemas.evidence import Evidence
from src.schemas.page import Page

logger = logging.getLogger(__name__)

# Initial lifecycle status for all Evidence records emitted by Phase 4.
_PENDING_STATUS: str = "pending"

# Recorded on every Evidence.extraction_method produced by this tool.
# Supports auditability (architecture.md §4.3).
_EXTRACTION_METHOD: str = "rule-based"


@dataclass(frozen=True)
class _ExtractionRule:
    """
    Associates a compiled regex pattern with an EvidenceType and field name.

    capture_group specifies which regex group contains the extracted value.
    The start and end positions of that group within Page.raw_text become
    source_start_char and source_end_char on the emitted Evidence record,
    satisfying the exact-span provenance requirement (architecture.md §5.3,
    requirements.md FR-10).

    extraction_confidence reflects the expected accuracy of this pattern and
    is distinct from ocr_confidence, which is inherited from the Page record
    (requirements.md SR-9, architecture.md §4.3).
    """

    evidence_type: EvidenceType
    field_name: str
    pattern: re.Pattern[str]
    capture_group: int
    extraction_confidence: float


# ---------------------------------------------------------------------------
# Section heading patterns
# ---------------------------------------------------------------------------
# Used by _detect_section() to identify which source heading a match
# falls within.  The emitted section value is the exact matched source
# text, not a normalized label.
_SECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"discharge\s+diagnos(?:is|es)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"(?:admitting|admission)\s+diagnosis", re.IGNORECASE | re.MULTILINE),
    re.compile(
        r"discharge\s+medications?|medications?\s+on\s+discharge",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"medications?\s+on\s+admission", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^medications?\s*:?\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"allerg(?:y|ies)\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(
        r"lab(?:oratory)?\s+results?\s*:|labs?\s*:",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"follow[\s\-]?up\s+instructions?\s*:|follow[\s\-]?up\s*:",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"pending\s+results?\s*:|results?\s+pending\s*:",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"patient\s+information\s*:|demographics?\s*:",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"vital\s+signs?\s*:", re.IGNORECASE | re.MULTILINE),
)


# ---------------------------------------------------------------------------
# Extraction rules
# ---------------------------------------------------------------------------
# Applied in order against Page.raw_text.  The span of capture_group
# within raw_text becomes the exact-span provenance on each emitted Evidence.
# Patterns are compiled once at module load; extraction_confidence values
# reflect pattern specificity.
_RULES: tuple[_ExtractionRule, ...] = (
    # ── Diagnosis ─────────────────────────────────────────────────────────────
    # High-specificity qualifier variants (primary / secondary / etc.)
    # [ \t]* instead of \s* prevents the colon from spanning across newlines
    # and picking up the next line as the captured value.
    _ExtractionRule(
        evidence_type=EvidenceType.DIAGNOSIS,
        field_name="diagnosis",
        pattern=re.compile(
            r"(?:primary|secondary|principal|final|admitting)[ \t]+"
            r"diagnosis[ \t]*:[ \t]*([A-Za-z][^\n\r,;]{2,79})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.90,
    ),
    # General diagnosis label
    _ExtractionRule(
        evidence_type=EvidenceType.DIAGNOSIS,
        field_name="diagnosis",
        pattern=re.compile(
            r"(?:diagnosis|diagnoses|dx)[ \t]*:[ \t]*([A-Za-z][^\n\r,;]{2,79})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.85,
    ),
    # ── Medication ────────────────────────────────────────────────────────────
    # Medication listed immediately after the "Medications:" header on the
    # same line.
    _ExtractionRule(
        evidence_type=EvidenceType.MEDICATION,
        field_name="medication_name",
        pattern=re.compile(
            r"^medications?[ \t]*:[ \t]*"
            r"([A-Za-z][A-Za-z0-9 \-]+\d+[ \t]*(?:mg|mcg|g|mL|units?))",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.82,
    ),
    # Medication on a bullet-pointed line
    _ExtractionRule(
        evidence_type=EvidenceType.MEDICATION,
        field_name="medication_name",
        pattern=re.compile(
            r"^[-•*][ \t]*"
            r"([A-Za-z][A-Za-z0-9 \-]+\d+[ \t]*(?:mg|mcg|g|mL|units?)[^\n\r]{0,40})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.75,
    ),
    # ── Allergy ───────────────────────────────────────────────────────────────
    _ExtractionRule(
        evidence_type=EvidenceType.ALLERGY,
        field_name="allergy_substance",
        pattern=re.compile(
            r"(?:allerg(?:y|ies)|drug[ \t]+allerg(?:y|ies))(?:[ \t]+to)?[ \t]*:[ \t]*"
            r"([A-Za-z][^\n\r,;]{2,59})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.88,
    ),
    # ── Lab result ────────────────────────────────────────────────────────────
    # Matches patterns like "WBC: 7.5 k/uL" or "Hemoglobin: 13.2 g/dL".
    # [ \t]* prevents the colon from bridging across newlines.
    _ExtractionRule(
        evidence_type=EvidenceType.LAB_RESULT,
        field_name="lab_result",
        pattern=re.compile(
            r"([A-Za-z][A-Za-z0-9 \-/]{1,19}[ \t]*:[ \t]*\d+\.?\d*[ \t]*"
            r"(?:mg/dL|g/dL|mmol/L|mEq/L|k/uL|U/L|%|IU/L|ng/mL|pg/mL))",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.80,
    ),
    # ── Demographic — date of birth ───────────────────────────────────────────
    _ExtractionRule(
        evidence_type=EvidenceType.DEMOGRAPHIC,
        field_name="date_of_birth",
        pattern=re.compile(
            r"(?:dob|date[ \t]+of[ \t]+birth|birth[ \t]+date)[ \t]*:[ \t]*"
            r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.92,
    ),
    # ── Demographic — patient name ────────────────────────────────────────────
    _ExtractionRule(
        evidence_type=EvidenceType.DEMOGRAPHIC,
        field_name="patient_name",
        pattern=re.compile(
            r"patient(?:[ \t]+name)?[ \t]*:[ \t]*([A-Za-z][A-Za-z \-',]{2,39})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.85,
    ),
    # ── Demographic — MRN ────────────────────────────────────────────────────
    _ExtractionRule(
        evidence_type=EvidenceType.DEMOGRAPHIC,
        field_name="mrn",
        pattern=re.compile(
            r"(?:mrn|medical[ \t]+record[ \t]+(?:number|no\.?))[ \t]*:[ \t]*"
            r"([A-Za-z0-9\-]{4,20})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.92,
    ),
    # ── Follow-up — explicit label ────────────────────────────────────────────
    _ExtractionRule(
        evidence_type=EvidenceType.FOLLOW_UP,
        field_name="follow_up_instruction",
        pattern=re.compile(
            r"follow[\t \-]?up(?:[ \t]+in|[ \t]+with|[ \t]+appointment)?[ \t]*:[ \t]*"
            r"([^\n\r]{5,119})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.80,
    ),
    # ── Follow-up — return-to-clinic phrasing ────────────────────────────────
    _ExtractionRule(
        evidence_type=EvidenceType.FOLLOW_UP,
        field_name="follow_up_instruction",
        pattern=re.compile(
            r"(return[ \t]+(?:to[ \t]+)?(?:clinic|office|hospital)(?:[^\n\r]{0,80}))",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.75,
    ),
    # ── Pending result — explicit label ───────────────────────────────────────
    # Matches "Pending: X", "Awaiting: X", or "Pending results: X".
    # The results? sub-word is optional so "Pending:" matches directly.
    _ExtractionRule(
        evidence_type=EvidenceType.PENDING_RESULT,
        field_name="pending_result_description",
        pattern=re.compile(
            r"(?:pending|awaiting)(?:[ \t]+results?)?[ \t]*:[ \t]*([^\n\r]{3,99})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.82,
    ),
    # ── Pending result — implicit phrasing ("X results pending") ─────────────
    # [ \t]+ instead of \s+ keeps the match on a single line and prevents
    # cross-paragraph false positives.
    _ExtractionRule(
        evidence_type=EvidenceType.PENDING_RESULT,
        field_name="pending_result_description",
        pattern=re.compile(
            r"([A-Za-z][A-Za-z0-9 \-/]{3,39}[ \t]+(?:results?[ \t]+)?pending"
            r"[^\n\r]{0,50})",
            re.IGNORECASE | re.MULTILINE,
        ),
        capture_group=1,
        extraction_confidence=0.75,
    ),
)


def _detect_section(raw_text: str, position: int) -> str:
    """
    Return the most recent source section heading before position in raw_text.

    Scans all section heading patterns and returns the exact matched source
    text whose match ends latest while still starting before position.
    Returns an empty string when no section heading precedes position.

    Parameters
    ----------
    raw_text:
        Full OCR text of the page.
    position:
        Character offset of the extraction match start within raw_text.

    Returns
    -------
    str
        The most recent exact source heading text, or "" if none found.
    """
    current_section = ""
    latest_end = -1
    for pattern in _SECTION_PATTERNS:
        for match in pattern.finditer(raw_text):
            # Use <= so that a heading whose match ends exactly at `position`
            # (or that the value immediately follows) is included.
            if match.start() <= position and match.end() > latest_end:
                latest_end = match.end()
                current_section = match.group(0).strip()
    return current_section


class EvidenceExtractionTool:
    """
    Rule-based extractor that produces Evidence records from a single Page.

    This tool is the Phase 4 Evidence Extraction implementation.  It applies
    compiled regex rules to Page.raw_text and emits Evidence records in
    memory.  It has no storage dependency and performs no validation,
    persistence, or deduplication.

    Consumer: EvidenceExtractionService (src/services/).
    Citation:  architecture.md §3.4, §6; requirements.md FR-9 through FR-12;
               implementation_plan.md Phase 4.
    """

    def extract_from_page(self, page: Page) -> list[Evidence]:
        """
        Apply all extraction rules to a single Page and return Evidence records.

        Consumer: EvidenceExtractionService.extract_for_patient() and
                  EvidenceExtractionService.extract_for_document().
        Citation:
            architecture.md §3.4:
                'Reads pages from the Page Store and emits structured
                Evidence records. Extraction never produces an evidence record
                without a complete provenance triplet.'
            requirements.md FR-9:
                'The Evidence Extraction Tool shall read from the Page Store
                and emit Evidence records.'
            requirements.md FR-10:
                'Every Evidence record shall carry an exact-span provenance
                triplet: document_name, page_number, source_text together
                with source_start_char and source_end_char.'
            requirements.md FR-11:
                'The Evidence Extraction Tool shall not emit any record
                lacking the complete provenance set.'
            requirements.md FR-12:
                'Every Evidence record shall carry both ocr_confidence
                (confidence in text recognition) and extraction_confidence
                (confidence in structured extraction).'

        Provenance guarantee:
            - source_text is set to page.raw_text (architecture.md §4.2).
            - source_start_char and source_end_char are the span of the
              matched capture group within source_text after stripping
              leading and trailing whitespace from the captured value.
            - ocr_confidence is carried forward from page.ocr_confidence.
            - evidence_id is a freshly generated UUID4 for each record.

        Error handling:
            Candidates that fail Evidence schema construction (ValidationError
            or ValueError) are logged at DEBUG level and skipped.  Processing
            continues across all remaining rules and matches, so a single
            malformed candidate never aborts the batch (FR-11 — incomplete
            provenance causes a skip, not a halt).

        Parameters
        ----------
        page:
            A Page record read from the Page Store.  page.raw_text is the
            extraction substrate.  page.patient_id, page.document_name, and
            page.page_number are carried forward as provenance on every
            emitted Evidence record.

        Returns
        -------
        list[Evidence]
            Zero or more Evidence records extracted from page.  Each record
            has status='pending' and has not been validated or persisted.
            The list may be empty when no rules match the page text.
        """
        records: list[Evidence] = []
        raw_text = page.raw_text

        for rule in _RULES:
            for match in rule.pattern.finditer(raw_text):
                try:
                    raw_value = match.group(rule.capture_group)
                    stripped_value = raw_value.strip()
                    if not stripped_value:
                        continue

                    # Adjust span to exclude stripped whitespace so that
                    # source_text[source_start_char:source_end_char] equals
                    # stripped_value exactly.
                    leading = len(raw_value) - len(raw_value.lstrip())
                    trailing = len(raw_value) - len(raw_value.rstrip())
                    start = match.start(rule.capture_group) + leading
                    end = match.end(rule.capture_group) - trailing

                    if end <= start:
                        continue

                    # Pass the adjusted start of the captured value so that
                    # a section heading on the same line (e.g. "Allergies:
                    # Penicillin") is correctly included as the current section
                    # rather than excluded by a strict < comparison.
                    section = _detect_section(raw_text, start)

                    record = Evidence(
                        evidence_id=str(uuid.uuid4()),
                        patient_id=page.patient_id,
                        evidence_type=rule.evidence_type,
                        field_name=rule.field_name,
                        field_value=stripped_value,
                        document_name=page.document_name,
                        page_number=page.page_number,
                        source_text=raw_text,
                        source_start_char=start,
                        source_end_char=end,
                        section=section,
                        ocr_confidence=page.ocr_confidence,
                        extraction_confidence=rule.extraction_confidence,
                        extraction_method=_EXTRACTION_METHOD,
                        status=_PENDING_STATUS,
                    )
                    records.append(record)

                except (ValidationError, ValueError, IndexError):
                    logger.debug(
                        "Skipped malformed extraction candidate for field=%s",
                        rule.field_name,
                    )

        return records
