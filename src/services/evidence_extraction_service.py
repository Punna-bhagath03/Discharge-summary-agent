"""
EvidenceExtractionService — Phase 4: Evidence Extraction pipeline.

Architecture reference:
  architecture.md §6:
    'src/services/ — higher-level orchestrations that compose tools
    (extraction pipeline, validation pipeline, reconciliation,
    conflict detection, summary generation).'

  implementation_plan.md Phase 4:
    Primary Module(s): src/tools/, src/services/

  implementation_plan.md Phase 5 (sequencing):
    'Phase 5 (Validation) depends on Phase 4 and is the gate to the
    Evidence Store.'

This service is the extraction pipeline orchestration.  It reads Page
records from StorageService, delegates per-page extraction to
EvidenceExtractionTool, and returns the aggregated list of Evidence
records in memory.

Phase 4 boundary — this service ONLY:
  - Reads Page records from StorageService.
  - Calls EvidenceExtractionTool.extract_from_page() for each page.
  - Aggregates and returns Evidence records in memory.

It does NOT:
  - Call save_evidence() (owned by Phase 5 via Evidence Validation).
  - Validate Evidence (owned by Phase 5).
  - Deduplicate Evidence (owned by Phase 5, FR-15).
  - Create ReviewFlags (owned by Phase 5 and later tool phases).
  - Mutate AgentState (owned by Phases 9/11).
  - Emit TraceSteps (owned by Phase 12).
"""

import logging

from src.schemas.evidence import Evidence
from src.storage.storage_service import StorageService
from src.tools.evidence_extraction_tool import EvidenceExtractionTool

logger = logging.getLogger(__name__)


class EvidenceExtractionService:
    """
    Extraction pipeline orchestration for Phase 4.

    Reads all Page records for a patient (or a single document) from the
    Page Store via StorageService, feeds each Page to EvidenceExtractionTool,
    and returns the combined list of Evidence records in memory.

    Consumer: Phase 5 Evidence Validation (EvidenceValidationService, to be
              implemented in Phase 5).  The Validation Service receives this
              list and gates admission to the Evidence Store.

    Citation: architecture.md §6; implementation_plan.md Phase 4 and Phase 5
              sequencing constraint.
    """

    def __init__(
        self,
        storage: StorageService,
        tool: EvidenceExtractionTool | None = None,
    ) -> None:
        """
        Initialise the extraction pipeline service.

        Parameters
        ----------
        storage:
            StorageService instance used to read Page records.  Storage reads
            are limited to get_pages_for_patient() and get_pages_for_document()
            in line with the Phase 4 allowed storage operations.
        tool:
            EvidenceExtractionTool instance.  When None a default-constructed
            instance is used.  Accepting an injected tool supports independent
            testability (requirements.md NFR-5).
        """
        self._storage = storage
        self._tool = tool if tool is not None else EvidenceExtractionTool()

    def extract_for_patient(self, patient_id: str) -> list[Evidence]:
        """
        Extract Evidence records from all Pages stored for patient_id.

        Consumer: Phase 5 Evidence Validation Service.
        Citation:
            architecture.md §3.4:
                'Evidence Extraction Tool reads pages from the Page Store.'
            requirements.md FR-9:
                'The Evidence Extraction Tool shall read from the Page Store
                and emit Evidence records.'
            implementation_plan.md Phase 4 exit criteria:
                'Evidence records are produced from the Page Store with full
                exact-span provenance; no record is emitted without it.'
            implementation_plan.md §5:
                'Phase 5 (Validation) depends on Phase 4.'

        Reads pages via StorageService.get_pages_for_patient(), which returns
        them sorted by (document_name, page_number), preserving document order
        in the returned Evidence list.

        Parameters
        ----------
        patient_id:
            Stable identifier of the Patient whose Pages are to be processed.
            Architecture §3.1, SR-4.

        Returns
        -------
        list[Evidence]
            All Evidence records extracted across every Page belonging to
            patient_id, in (document_name, page_number) order.  Records have
            status='pending' and have not been validated or persisted.
            Returns an empty list when no Pages are stored for the patient.
        """
        pages = self._storage.get_pages_for_patient(patient_id)
        if not pages:
            logger.debug("extract_for_patient: no pages found")
            return []

        records: list[Evidence] = []
        for page in pages:
            page_records = self._tool.extract_from_page(page)
            records.extend(page_records)
            logger.debug(
                "extract_for_patient: extracted %d records from page",
                len(page_records),
            )

        logger.debug(
            "extract_for_patient: extracted %d records total",
            len(records),
        )
        return records

    def extract_for_document(
        self,
        patient_id: str,
        document_name: str,
    ) -> list[Evidence]:
        """
        Extract Evidence records from all Pages of a single document.

        Consumer: Phase 5 Evidence Validation Service (document-scoped
                  extraction path).
        Citation:
            architecture.md §3.4:
                'Evidence Extraction Tool reads pages from the Page Store.'
            architecture.md §4.2:
                'document_name and page_number together address the page
                within a document and are the provenance keys that Evidence
                records carry forward.'
            requirements.md FR-6:
                'The Page Store shall persist Page records addressed by
                (patient_id, document_name, page_number).'
            StorageService.get_pages_for_document() is an explicitly
            supported Phase 2 operation.

        Reads pages via StorageService.get_pages_for_document(), which returns
        them sorted by page_number.

        Parameters
        ----------
        patient_id:
            Stable identifier of the owning Patient.
        document_name:
            Name of the document whose Pages are to be processed.  Must match
            the document_name stored on Page records.

        Returns
        -------
        list[Evidence]
            All Evidence records extracted from every Page in the named
            document, in page_number order.  Records have status='pending'
            and have not been validated or persisted.  Returns an empty list
            when no Pages are stored for the (patient_id, document_name) pair.
        """
        pages = self._storage.get_pages_for_document(patient_id, document_name)
        if not pages:
            logger.debug("extract_for_document: no pages found")
            return []

        records: list[Evidence] = []
        for page in pages:
            page_records = self._tool.extract_from_page(page)
            records.extend(page_records)
            logger.debug(
                "extract_for_document: extracted %d records from page",
                len(page_records),
            )

        logger.debug(
            "extract_for_document: extracted %d records total",
            len(records),
        )
        return records
