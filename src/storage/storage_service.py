"""
StorageService — Phase 2 in-memory storage layer.

This is the ONLY component in the system permitted to read from or write
to stored artifacts.  Every other component in every later phase — OCR
Tool, Evidence Extraction Tool, Evidence Validation Tool, agent-loop tools,
Trace System, Summary Generator — calls StorageService.  No component may
bypass it or maintain its own store.

Architecture reference — implementation_plan.md §4 Phase 2:
  'The storage layer is the only component permitted to write to or read
  from durable storage; every other component goes through it.'

NFR-8 (requirements.md §5.4):
  'Storage backends shall be replaceable without changing upstream or
  downstream stages.'
  The public method signatures below define the replaceable contract.  The
  in-memory backend can be swapped for a persistent one without touching
  any caller.

Backend: Python dicts and lists (in-memory).
Thread safety: not provided.  The architecture is single-process; concurrency
is out of scope.
"""

from src.schemas.conflict import Conflict
from src.schemas.enums import EvidenceType
from src.schemas.evidence import Evidence
from src.schemas.page import Page
from src.schemas.patient import Patient
from src.schemas.review_flag import ReviewFlag
from src.schemas.trace_step import TraceStep


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StorageError(Exception):
    """Base class for all StorageService errors."""


class PatientAlreadyExistsError(StorageError):
    """
    Raised by save_patient() when the patient_id is already registered.

    Architecture: A Patient record is registered exactly once at ingestion
    (architecture.md §3.1, requirements.md FR-2).  A duplicate patient_id
    indicates a caller error.
    """


class EvidenceAlreadyExistsError(StorageError):
    """
    Raised by save_evidence() when the evidence_id is already stored.

    Architecture: Evidence records are immutable once admitted to the
    Evidence Store (architecture.md §3.6, FR-23).  Duplicate evidence_ids
    indicate either a caller error or a de-duplication failure in Evidence
    Validation.
    """


class ReviewFlagAlreadyExistsError(StorageError):
    """
    Raised by save_review_flag() when the flag_id is already stored.

    Architecture: ReviewFlag records are created once; no update or delete
    operation exists (architecture.md §4.5, §5.5).  Duplicate flag_ids
    indicate a caller error.
    """


# ---------------------------------------------------------------------------
# StorageService
# ---------------------------------------------------------------------------


class StorageService:
    """
    Single in-memory storage service for the Discharge Summary Agent.

    All Phase 2 storage operations are methods of this class.  There is no
    abstract base class, repository pattern, or generic CRUD layer — the
    method signatures are themselves the storage contract that every later
    phase depends on.

    Internal storage layout
    -----------------------
    _patients                  : patient_id  → Patient
    _pages                     : (patient_id, document_name, page_number) → Page
    _evidence                  : evidence_id → Evidence          (primary)
    _evidence_patient_index    : patient_id  → [evidence_id …]  (index)
    _conflicts                 : patient_id  → [Conflict …]     (grouped)
    _conflict_id_index         : conflict_id → Conflict          (primary)
    _review_flags              : flag_id     → ReviewFlag         (primary)
    _review_flags_patient_index: patient_id  → [flag_id …]       (index)
    _trace                     : patient_id  → [TraceStep …]     (append-only)
    """

    def __init__(self) -> None:
        # Patient store — primary index
        self._patients: dict[str, Patient] = {}

        # Page store — composite key matches FR-6 address scheme
        self._pages: dict[tuple[str, str, int], Page] = {}

        # Evidence store — primary index + patient grouping index
        self._evidence: dict[str, Evidence] = {}
        self._evidence_patient_index: dict[str, list[str]] = {}

        # Conflict store — grouped by patient_id + primary index by conflict_id
        self._conflicts: dict[str, list[Conflict]] = {}
        self._conflict_id_index: dict[str, Conflict] = {}

        # Review flag store — primary index + patient grouping index
        self._review_flags: dict[str, ReviewFlag] = {}
        self._review_flags_patient_index: dict[str, list[str]] = {}

        # Trace store — append-only lists, grouped by patient_id
        self._trace: dict[str, list[TraceStep]] = {}

    # ==========================================================================
    # PATIENT
    # ==========================================================================

    def save_patient(self, patient: Patient) -> None:
        """
        Register a new Patient record.

        A Patient record is registered exactly once at ingestion and anchors
        every subsequent artifact (Page, Evidence, Conflict, ReviewFlag,
        AgentState, TraceStep, DischargeSummary) via patient_id.

        Architecture: §3.1, §4.1, FR-2.

        Raises:
            PatientAlreadyExistsError: if patient.patient_id is already stored.
        """
        if patient.patient_id in self._patients:
            raise PatientAlreadyExistsError(
                f"Patient '{patient.patient_id}' is already registered.  "
                "Each patient_id must be unique across the system."
            )
        self._patients[patient.patient_id] = patient

    def get_patient(self, patient_id: str) -> Patient | None:
        """
        Return the Patient record for patient_id, or None if not found.

        All other components that need to verify a patient reference or
        read patient-level metadata call this method.

        Architecture: §4.1, SR-4 — all artifacts reference a Patient via
        patient_id; this is the lookup that resolves those references.
        """
        return self._patients.get(patient_id)

    # ==========================================================================
    # PAGE
    # ==========================================================================

    def save_page(self, page: Page) -> None:
        """
        Persist or overwrite a Page record.

        The Page Store is the canonical store of OCR output.  Two callers
        are permitted to write here:
          1. The OCR Tool, which creates Page records after initial OCR.
          2. The OCR Retry Tool, which overwrites a specific Page record after
             re-processing it with an updated ocr_confidence and raw_text.

        Overwrite semantics are intentional: the OCR Retry Tool re-invokes
        OCR on the stored page_image_path and writes the improved Page back
        to the same key.

        Architecture: §3.2, §3.3, §3.8, FR-6, FR-8.
        Key: (patient_id, document_name, page_number).
        """
        key = (page.patient_id, page.document_name, page.page_number)
        self._pages[key] = page

    def get_page(
        self,
        patient_id: str,
        document_name: str,
        page_number: int,
    ) -> Page | None:
        """
        Return the Page record addressed by (patient_id, document_name,
        page_number), or None if it has not been stored yet.

        Primary callers:
          - OCR Retry Tool: fetches the stored page_image_path for a specific
            low-confidence page before re-invoking OCR (FR-8, §3.8).
          - Evidence Extraction Tool: reads raw_text for individual pages.

        Architecture: §3.3, §4.2, FR-6.
        """
        return self._pages.get((patient_id, document_name, page_number))

    def get_pages_for_patient(self, patient_id: str) -> list[Page]:
        """
        Return all Page records belonging to patient_id, sorted by
        (document_name, page_number).

        The Evidence Extraction Tool reads the full page set for a patient
        when processing all documents in sequence.

        Architecture: §3.4, FR-9 — 'the Evidence Extraction Tool reads pages
        from the Page Store.'

        Returns an empty list if no pages have been stored for the patient.
        """
        pages = [
            page
            for (pid, _doc, _num), page in self._pages.items()
            if pid == patient_id
        ]
        return sorted(pages, key=lambda p: (p.document_name, p.page_number))

    def get_pages_for_document(
        self,
        patient_id: str,
        document_name: str,
    ) -> list[Page]:
        """
        Return all Page records for (patient_id, document_name), sorted by
        page_number.

        Used when the Evidence Extraction Tool processes one document at a
        time, and when the OCR Retry Tool needs all low-confidence pages
        within a single document.

        Architecture: §3.4, §3.8, FR-6 — pages are addressed by the
        composite key (patient_id, document_name, page_number).

        Returns an empty list if no matching pages exist.
        """
        pages = [
            page
            for (pid, doc, _num), page in self._pages.items()
            if pid == patient_id and doc == document_name
        ]
        return sorted(pages, key=lambda p: p.page_number)

    # ==========================================================================
    # EVIDENCE
    # ==========================================================================

    def save_evidence(self, evidence: Evidence) -> None:
        """
        Admit a validated Evidence record to the Evidence Store.

        This is the ONLY write path into the Evidence Store (§3.6).  The
        Evidence Validation Tool is the only permitted caller.  No other
        component may write Evidence records.

        Patient grouping is read from evidence.patient_id, which is a
        required field on the Evidence schema (§4.1, §4.3, SR-4, SR-7a).

        Architecture: §3.5, §3.6, FR-22, FR-23 — 'the Evidence Store shall
        persist only validated Evidence.'

        Raises:
            EvidenceAlreadyExistsError: if evidence.evidence_id is already
                stored.  Evidence records are immutable once admitted.
        """
        if evidence.evidence_id in self._evidence:
            raise EvidenceAlreadyExistsError(
                f"Evidence '{evidence.evidence_id}' is already in the Evidence "
                "Store.  Evidence records are immutable once admitted."
            )
        self._evidence[evidence.evidence_id] = evidence
        self._evidence_patient_index.setdefault(evidence.patient_id, []).append(
            evidence.evidence_id
        )

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """
        Return the Evidence record for evidence_id, or None if not found.

        Used to resolve individual evidence_id references from Conflict
        records, ReviewFlag records, and DischargeSummary.supporting_evidence_ids.

        Architecture: §4.4, §4.5, §4.8; acceptance criteria §8 — the
        reviewer path from DischargeSummary → supporting_evidence_ids →
        Evidence requires individual lookup.
        """
        return self._evidence.get(evidence_id)

    def get_evidence_for_patient(self, patient_id: str) -> list[Evidence]:
        """
        Return all validated Evidence records for patient_id, in insertion
        order.

        This is the primary read surface for the agent loop and Summary
        Generator.  Multiple agent-loop tools call this:
          - Missing Data Tool: checks which required fields lack Evidence.
          - Conflict Detection Tool: scans all Evidence for the same field.
          - Medication Reconciliation Tool: reads MEDICATION evidence.
          - Pending Results Tool: reads PENDING_RESULT evidence.
          - Summary Generator: reads all validated Evidence to compose the
            DischargeSummary.
          - Evidence Validation Tool: reads existing records to detect
            duplicate evidence (FR-15).

        Architecture: §3.6 — 'the Evidence Store is the only input surface
        for the agent loop and the summary generator'; §5.9; FR-15.

        Returns an empty list if no Evidence has been stored for the patient.
        """
        evidence_ids = self._evidence_patient_index.get(patient_id, [])
        return [self._evidence[eid] for eid in evidence_ids]

    def get_evidence_by_type(
        self,
        patient_id: str,
        evidence_type: EvidenceType,
    ) -> list[Evidence]:
        """
        Return all validated Evidence records for patient_id whose
        evidence_type matches the given type.

        Callers:
          - Medication Reconciliation Tool (Phase 6): filters for
            EvidenceType.MEDICATION to consolidate medication evidence across
            documents while preserving all source references.
          - Pending Results Tool (Phase 8): filters for
            EvidenceType.PENDING_RESULT to surface pending clinical results as
            ReviewFlag records.

        Architecture: §3.8, FR-29, FR-30; §4.3 — evidence_type is the
        signal that routes Evidence to the correct agent tool.

        Returns an empty list if no matching Evidence exists.
        """
        return [
            ev
            for ev in self.get_evidence_for_patient(patient_id)
            if ev.evidence_type == evidence_type
        ]

    def get_evidence_by_provenance(
        self,
        patient_id: str,
        document_name: str,
        page_number: int,
        source_start_char: int,
        source_end_char: int,
    ) -> list[Evidence]:
        """
        Return Evidence records for patient_id whose provenance span exactly
        matches (document_name, page_number, source_start_char, source_end_char).

        This operation exists solely to support de-duplication in the Evidence
        Validation Tool (FR-15).  Equivalence between two Evidence records is
        determined by exact-span provenance, not by field_name or field_value.
        If this method returns a non-empty list for a candidate record, the
        Evidence Validation Tool must treat the candidate as a duplicate and
        reject it.

        Architecture: §3.5, FR-15 — 'detect and de-duplicate equivalent
        evidence'; §5.3 — exact-span provenance is the canonical identity
        signal for Evidence records.

        Returns an empty list if no matching Evidence exists.
        """
        return [
            ev
            for ev in self.get_evidence_for_patient(patient_id)
            if (
                ev.document_name == document_name
                and ev.page_number == page_number
                and ev.source_start_char == source_start_char
                and ev.source_end_char == source_end_char
            )
        ]

    # ==========================================================================
    # CONFLICT
    # ==========================================================================

    def save_conflict(self, conflict: Conflict) -> None:
        """
        Persist a Conflict record produced by the Conflict Detection Tool.

        Patient grouping is read from conflict.patient_id, which is a required
        field on the Conflict schema (§4.1, §4.4, SR-4, SR-11b).
        Individual lookup by conflict_id is supported via _conflict_id_index.

        Architecture: §3.8, FR-28; implementation_plan Phase 2 — save_conflict()
        is an explicitly named required storage operation.
        """
        self._conflicts.setdefault(conflict.patient_id, []).append(conflict)
        self._conflict_id_index[conflict.conflict_id] = conflict

    def get_conflict(self, conflict_id: str) -> Conflict | None:
        """
        Return the Conflict record for conflict_id, or None if not found.

        Individual lookup is now supported because Conflict carries a
        conflict_id field (§4.4, SR-11a).  This enables trace replay and
        audit tools to resolve Conflict references individually.

        Architecture: §4.4, SR-11a — conflict_id uniquely identifies the
        record.
        """
        return self._conflict_id_index.get(conflict_id)

    def get_conflicts_for_patient(self, patient_id: str) -> list[Conflict]:
        """
        Return all Conflict records for patient_id, in detection order.

        Used to populate AgentState.conflicts when the agent loop initialises
        or refreshes state.  The Planner uses this list to decide whether to
        invoke the Conflict Detection Tool or Medication Reconciliation Tool.

        Architecture: §3.7, §4.6 — AgentState.conflicts holds self-contained
        Conflict objects; §5.4 — conflicts are never silently resolved, so
        they must persist and be available to the planner across iterations.

        Returns an empty list if no Conflicts have been stored for the patient.
        """
        return list(self._conflicts.get(patient_id, []))

    # ==========================================================================
    # REVIEW FLAG
    # ==========================================================================

    def save_review_flag(self, flag: ReviewFlag) -> None:
        """
        Persist a ReviewFlag record.

        ReviewFlag records are produced by multiple tools:
          - Evidence Validation Tool: for rejected-but-clinically-relevant
            Evidence (§3.5, FR-22).
          - Review Flag Tool: for general agent-loop review conditions (§3.8).
          - Missing Data Tool: for required fields without supporting Evidence.
          - Conflict Detection Tool: to surface Conflict records for human review.
          - Pending Results Tool: for clinical results marked as pending.

        Patient grouping is read from flag.patient_id, which is a required
        field on the ReviewFlag schema (§4.1, §4.5, SR-4, SR-14a).

        Architecture: §4.5, §5.5; implementation_plan Phase 2 — save_review_flag()
        is an explicitly named required storage operation.

        Raises:
            ReviewFlagAlreadyExistsError: if flag.flag_id is already stored.
        """
        if flag.flag_id in self._review_flags:
            raise ReviewFlagAlreadyExistsError(
                f"ReviewFlag '{flag.flag_id}' is already stored.  "
                "ReviewFlag records are created once and never updated."
            )
        self._review_flags[flag.flag_id] = flag
        self._review_flags_patient_index.setdefault(flag.patient_id, []).append(
            flag.flag_id
        )

    def get_review_flag(self, flag_id: str) -> ReviewFlag | None:
        """
        Return the ReviewFlag record for flag_id, or None if not found.

        Used to resolve individual flag_id references from AgentState.review_flags
        (which stores IDs, not embedded objects) and from
        DischargeSummary.review_flags.

        Architecture: §4.6 — AgentState.review_flags stores IDs; §4.8 —
        DischargeSummary.review_flags is a list of flag identifiers that must
        resolve to full ReviewFlag objects.
        """
        return self._review_flags.get(flag_id)

    def get_review_flags_for_patient(self, patient_id: str) -> list[ReviewFlag]:
        """
        Return all ReviewFlag records for patient_id, in creation order.

        Primary callers:
          - Summary Generator (Phase 13): attaches the full review workload to
            the DischargeSummary before emitting it.
          - System output stage: emits the associated ReviewFlag set alongside
            the DischargeSummary and trace (FR-42).

        Architecture: §3.9, §5.5, FR-42 — 'the system shall emit the
        associated ReviewFlag set'; §4.8 — review flags are propagated into
        DischargeSummary.

        Returns an empty list if no ReviewFlags have been stored for the patient.
        """
        flag_ids = self._review_flags_patient_index.get(patient_id, [])
        return [self._review_flags[fid] for fid in flag_ids]

    # ==========================================================================
    # TRACE
    # ==========================================================================

    def save_trace(self, trace_step: TraceStep) -> None:
        """
        Append a TraceStep to the patient's trace.

        The trace store is append-only.  No existing TraceStep may be modified
        or removed.  The Trace System (Phase 12) is the only permitted caller.
        Every planner decision, executor action, tool invocation, and state
        transition produces exactly one call to this method.

        TraceStep carries its own patient_id field so no separate patient_id
        parameter is required.

        Architecture: §3.11, §5.6, FR-34; implementation_plan Phase 2 —
        save_trace() is an explicitly named required storage operation.
        """
        self._trace.setdefault(trace_step.patient_id, []).append(trace_step)

    def get_trace_for_patient(self, patient_id: str) -> list[TraceStep]:
        """
        Return the complete TraceStep sequence for patient_id, in recording
        order.

        Provides the full audit trail required by FR-37 and FR-43.  The
        sequence is sufficient to reconstruct every agent decision and every
        fact in the final DischargeSummary.

        Architecture: §3.11, FR-37, FR-43 — 'the system shall emit the full
        TraceStep sequence.'

        Returns an empty list if no trace steps have been recorded for the
        patient.
        """
        return list(self._trace.get(patient_id, []))

    def get_trace_for_iteration(
        self,
        patient_id: str,
        iteration: int,
    ) -> list[TraceStep]:
        """
        Return all TraceStep records for (patient_id, iteration), in recording
        order.

        Enables trace replay grouped by agent-loop iteration without loading
        the full trace.

        Architecture: SR-20 — 'iteration shall support replay grouped by
        agent-loop iteration'; FR-35 — 'every TraceStep shall include
        iteration so trace replay can be grouped by agent-loop iteration.'

        Returns an empty list if no trace steps exist for the given iteration.
        """
        return [
            step
            for step in self._trace.get(patient_id, [])
            if step.iteration == iteration
        ]
