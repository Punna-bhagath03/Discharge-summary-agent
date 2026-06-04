"""
EvidenceValidationService — Phase 5: Evidence Validation gate.

Architecture reference:
  architecture.md §3.5:
    'Evidence Validation is a first-class architectural component... It is
    the gate that protects the Evidence Store from polluted data.'
    Outputs: 'Validated Evidence persisted to the Evidence Store.'

  architecture.md §6:
    'src/services/ — higher-level orchestrations that compose tools
    (extraction pipeline, validation pipeline, ...).'

  requirements.md FR-15, FR-22, FR-23.

  implementation_plan.md Phase 5:
    'Validated Evidence — admitted to the Evidence Store via save_evidence().'
    'Only validated evidence reaches the Evidence Store; rejected records
    are either dropped or surfaced as review flags...'

This service is the validation pipeline orchestration.  It receives the
list[Evidence] produced by Phase 4, validates each record via
EvidenceValidationTool, deduplicates by exact-span provenance, persists
only validated Evidence via StorageService.save_evidence(), and drops
rejected records.

Phase 5 boundary — this service ONLY:
  - Validates Evidence (FR-13, FR-16 through FR-21 via the tool).
  - Deduplicates by exact-span provenance (FR-15).
  - Persists validated Evidence via save_evidence() (FR-23).

It does NOT:
  - Detect conflicts (Phase 7).
  - Reconcile medications (Phase 6).
  - Run pending-results workflows (Phase 8).
  - Mutate AgentState (Phases 9/11).
  - Run planner/executor logic (Phases 10/11).
  - Emit or persist TraceSteps / call save_trace() (Phase 12).
  - Generate summaries (Phase 13).
  - Write pages (OCR / OCR Retry).

Architecture-gap note — ReviewFlags:
  architecture.md §3.5 / FR-22 allow ReviewFlags for
  'rejected-but-clinically-relevant' records.  No document defines the
  clinical-relevance criteria, nor the ReviewFlag category/severity/status
  taxonomy required to construct one.  Constructing a ReviewFlag would
  therefore require inventing undefined values, which is prohibited.  Under
  the explicitly permitted alternative in implementation_plan.md Phase 5
  exit criteria ('rejected records are either dropped or surfaced as review
  flags'), this gate drops rejected records.  save_review_flag() is the
  documented persistence path and remains available once the taxonomy gap
  is resolved by an ADR.

NFR-9: logs contain only aggregate counts and PHI-free reason codes.  No
patient_id, document_name, page_number, field_value, source_text, or
exception payload is logged.
"""

import logging
from collections import Counter

from src.schemas.evidence import Evidence
from src.storage.storage_service import EvidenceAlreadyExistsError, StorageService
from src.tools.evidence_validation_tool import EvidenceValidationTool, RejectionReason

logger = logging.getLogger(__name__)


class EvidenceValidationService:
    """
    Validation pipeline orchestration for Phase 5.

    Consumer: the agent loop / executor (Phase 11), which wires the Phase 4
              extraction output into this gate and relies on the populated
              Evidence Store thereafter.
    Citation: architecture.md §3.5, §3.6, §6; requirements.md FR-15, FR-22,
              FR-23; implementation_plan.md Phase 5.
    """

    def __init__(
        self,
        storage: StorageService,
        tool: EvidenceValidationTool | None = None,
    ) -> None:
        """
        Initialise the validation gate.

        Parameters
        ----------
        storage:
            StorageService used to deduplicate against the Evidence Store
            (get_evidence_by_provenance) and to persist validated Evidence
            (save_evidence).
        tool:
            EvidenceValidationTool instance.  When None a default-constructed
            instance is used.  Injection supports independent testability
            (requirements.md NFR-5).
        """
        self._storage = storage
        self._tool = tool if tool is not None else EvidenceValidationTool()

    def validate_and_store(self, candidates: list[Evidence]) -> list[Evidence]:
        """
        Validate Phase 4 Evidence candidates and persist only valid records.

        Consumer: agent loop / executor (Phase 11).
        Citation:
            architecture.md §3.5:
                'It is the gate that protects the Evidence Store from
                polluted data.'
            requirements.md FR-15:
                'detect and de-duplicate equivalent evidence.'
            requirements.md FR-23:
                'The Evidence Store shall persist only validated Evidence.'
            implementation_plan.md Phase 5:
                'Validated Evidence — admitted to the Evidence Store via
                save_evidence().'

        Processing per candidate:
          1. Run EvidenceValidationTool.validate() (FR-13, FR-16–FR-21).
          2. If no per-record reasons, check exact-span duplication (FR-15)
             against both this batch and the Evidence Store via
             StorageService.get_evidence_by_provenance().
          3. Records with no reasons are persisted via save_evidence() and
             returned.  All others are dropped (Phase 5 exit criteria).

        Equivalence for FR-15 is exact-span provenance —
        (patient_id, document_name, page_number, source_start_char,
        source_end_char) — which is the identity the storage layer documents
        for de-duplication (StorageService.get_evidence_by_provenance,
        architecture.md §5.3).  No semantic deduplication is performed.

        Error handling:
          A candidate is never allowed to abort the batch.  If save_evidence()
          raises EvidenceAlreadyExistsError (an evidence_id already stored),
          the candidate is treated as a duplicate and dropped, and processing
          continues.

        Parameters
        ----------
        candidates:
            Evidence records emitted by Phase 4.  Not modified.

        Returns
        -------
        list[Evidence]
            The validated Evidence records admitted to the Evidence Store, in
            input order.  Rejected and duplicate records are omitted.
        """
        admitted: list[Evidence] = []
        rejection_counts: Counter[RejectionReason] = Counter()
        seen_spans: set[tuple[str, str, int, int, int]] = set()

        for candidate in candidates:
            reasons = self._tool.validate(candidate)

            if not reasons:
                span_key = (
                    candidate.patient_id,
                    candidate.document_name,
                    candidate.page_number,
                    candidate.source_start_char,
                    candidate.source_end_char,
                )
                if span_key in seen_spans or self._is_stored_duplicate(candidate):
                    reasons = [RejectionReason.DUPLICATE_EVIDENCE]

            if reasons:
                rejection_counts.update(reasons)
                continue

            try:
                self._storage.save_evidence(candidate)
            except EvidenceAlreadyExistsError:
                rejection_counts.update([RejectionReason.DUPLICATE_EVIDENCE])
                continue

            seen_spans.add(span_key)
            admitted.append(candidate)

        self._log_summary(len(candidates), len(admitted), rejection_counts)
        return admitted

    def _is_stored_duplicate(self, candidate: Evidence) -> bool:
        """
        Return True when an Evidence record with the same exact-span
        provenance already exists in the Evidence Store (FR-15).

        Citation: StorageService.get_evidence_by_provenance — documented as
        the FR-15 de-duplication support keyed on exact-span provenance.
        """
        existing = self._storage.get_evidence_by_provenance(
            candidate.patient_id,
            candidate.document_name,
            candidate.page_number,
            candidate.source_start_char,
            candidate.source_end_char,
        )
        return bool(existing)

    @staticmethod
    def _log_summary(
        total: int,
        admitted: int,
        rejection_counts: Counter[RejectionReason],
    ) -> None:
        """
        Emit a PHI-free DEBUG summary of the validation run (NFR-9).

        Only aggregate counts and reason-code names are logged; no
        patient-linked values are referenced.
        """
        logger.debug(
            "Evidence validation: %d candidates, %d admitted, %d rejected",
            total,
            admitted,
            total - admitted,
        )
        for reason, count in sorted(rejection_counts.items(), key=lambda kv: kv[0].value):
            logger.debug("Evidence validation rejection: %s=%d", reason.value, count)
