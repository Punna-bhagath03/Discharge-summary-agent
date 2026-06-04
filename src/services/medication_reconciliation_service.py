"""
MedicationReconciliationService — Phase 6: Medication Reconciliation pipeline.

Architecture reference:
  architecture.md §3.8:
    'Medication Reconciliation Tool — consolidates medication evidence
    across documents while preserving every source reference.'

  architecture.md §6:
    'src/services/ — higher-level orchestrations that compose tools
    (extraction pipeline, validation pipeline, reconciliation, ...).'

  requirements.md FR-29:
    'The agent shall provide a Medication Reconciliation Tool that
    consolidates medication evidence across documents while preserving
    every source reference.'

  implementation_plan.md Phase 6:
    'It consolidates medication evidence across documents and preserves
    every source reference.  Conflicting entries are not silently merged;
    they are forwarded to Phase 7.'

This service orchestrates the MedicationReconciliationTool.  It reads
validated medication Evidence from StorageService via
get_evidence_by_type(EvidenceType.MEDICATION), delegates to the tool,
and returns existing Evidence records in memory.

Phase 6 boundary — this service ONLY:
  - Reads validated medication Evidence from the Evidence Store.
  - Delegates to MedicationReconciliationTool.
  - Returns list[Evidence] in memory.

It does NOT:
  - Call save_evidence(), save_conflict(), save_review_flag(),
    save_trace(), or save_page().
  - Create Conflict records (Phase 7).
  - Create ReviewFlag records (Phase 7/8).
  - Normalize medication names, dosage, route, or frequency.
  - Choose a canonical medication record.
  - Remove provenance records.
  - Mutate AgentState.
  - Run planner/executor logic.
  - Generate summaries.

NFR-9: logs contain only aggregate counts and generic workflow events.
No patient_id, document_name, page_number, field_value, source_text,
or exception payload is logged.
"""

import logging

from src.schemas.enums import EvidenceType
from src.schemas.evidence import Evidence
from src.storage.storage_service import StorageService
from src.tools.medication_reconciliation_tool import MedicationReconciliationTool

logger = logging.getLogger(__name__)


class MedicationReconciliationService:
    """
    Medication reconciliation pipeline orchestration for Phase 6.

    Consumer: agent loop / executor (Phase 11), which wires the
              medication reconciliation step and hands disagreement
              candidates to Phase 7 (Conflict Detection).
    Citation: architecture.md §3.8, §6; requirements.md FR-29;
              implementation_plan.md Phase 6.
    """

    def __init__(
        self,
        storage: StorageService,
        tool: MedicationReconciliationTool | None = None,
    ) -> None:
        """
        Initialise the medication reconciliation service.

        Parameters
        ----------
        storage:
            StorageService used to read validated medication Evidence via
            get_evidence_by_type(EvidenceType.MEDICATION).
        tool:
            MedicationReconciliationTool instance.  When None a
            default-constructed instance is used.  Injection supports
            independent testability (requirements.md NFR-5).
        """
        self._storage = storage
        self._tool = tool if tool is not None else MedicationReconciliationTool()

    def reconcile_for_patient(
        self, patient_id: str
    ) -> list[Evidence]:
        """
        Read all validated medication Evidence for a patient and return
        a reconciled, in-memory Evidence view.

        Consumer: agent loop / executor (Phase 11).
        Citation:
            architecture.md §3.8:
                'consolidates medication evidence across documents while
                preserving every source reference.'
            requirements.md FR-29:
                'consolidates medication evidence across documents while
                preserving every source reference.'
            implementation_plan.md Phase 6:
                'Conflicting entries are not silently merged; they are
                forwarded to Phase 7.'

        Processing:
          1. Read all validated Evidence for patient_id with
             evidence_type == EvidenceType.MEDICATION from the Evidence
             Store via StorageService.get_evidence_by_type().
          2. Delegate to MedicationReconciliationTool.reconcile().
          3. Return existing Evidence records in memory.
             No write operations are performed.

        Empty input is handled: an empty list is returned when no medication
        Evidence exists.

        NFR-9: patient_id is not logged.

        Parameters
        ----------
        patient_id:
            Identifier of the owning Patient record.

        Returns
        -------
        list[Evidence]
            Existing Evidence records only; not persisted.  Records from
            consolidated groups are returned first, followed by records from
            internal disagreement-candidate groups.  No custom result contract
            is returned.
        """
        medication_evidence = self._storage.get_evidence_by_type(
            patient_id, EvidenceType.MEDICATION
        )

        if not medication_evidence:
            logger.debug(
                "medication_reconciliation: no medication evidence found"
            )
            return []

        result = self._tool.reconcile(medication_evidence)
        consolidated_count, disagreement_candidate_count = self._count_groups(
            medication_evidence
        )

        logger.debug(
            "medication_reconciliation: processed %d medication records, "
            "%d consolidated, %d disagreement candidates",
            len(medication_evidence),
            consolidated_count,
            disagreement_candidate_count,
        )

        return result

    @staticmethod
    def _count_groups(
        medication_evidence: list[Evidence],
    ) -> tuple[int, int]:
        """
        Return aggregate counts for privacy-safe logging.

        This does not create an inter-component contract and does not affect
        reconciliation output.
        """
        groups: dict[str, list[Evidence]] = {}
        for ev in medication_evidence:
            groups.setdefault(ev.field_name, []).append(ev)

        consolidated_count = 0
        disagreement_candidate_count = 0
        for records in groups.values():
            distinct_values = {ev.field_value for ev in records}
            if len(distinct_values) == 1:
                consolidated_count += len(records)
            else:
                disagreement_candidate_count += len(records)

        return consolidated_count, disagreement_candidate_count
