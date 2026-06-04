"""
PendingResultsService — Phase 8: Pending Results Detection pipeline.

Architecture reference:
  requirements.md FR-30; implementation_plan.md Phase 8.

Normative policy: docs/adr/ADR-017.md.

NFR-9: aggregate logging only.
"""

from __future__ import annotations

import logging

from src.schemas.enums import EvidenceType
from src.schemas.review_flag import ReviewFlag
from src.storage.storage_service import StorageService
from src.tools.pending_results_tool import PendingResultsTool

logger = logging.getLogger(__name__)


class PendingResultsService:
    """
    Pending results pipeline for Phase 8.

    Consumer: Executor (Phase 11).
    """

    def __init__(
        self,
        storage: StorageService,
        tool: PendingResultsTool | None = None,
    ) -> None:
        self._storage = storage
        self._tool = tool if tool is not None else PendingResultsTool()

    def detect_for_patient(self, patient_id: str) -> list[ReviewFlag]:
        """
        Surface pending clinical results as ReviewFlags for a patient.

        Storage read: get_evidence_by_type(PENDING_RESULT).
        Storage write: save_review_flag() per flag.

        Returns persisted ReviewFlag records from this invocation.
        """
        pending_evidence = self._storage.get_evidence_by_type(
            patient_id, EvidenceType.PENDING_RESULT
        )
        flags = self._tool.detect(pending_evidence)

        for flag in flags:
            self._storage.save_review_flag(flag)

        logger.debug(
            "pending_results: processed %d pending evidence records, "
            "emitted %d review flags",
            len(pending_evidence),
            len(flags),
        )

        return flags
