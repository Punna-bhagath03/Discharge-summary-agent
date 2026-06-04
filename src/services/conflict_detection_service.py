"""
ConflictDetectionService — Phase 7: Conflict Detection pipeline.

Architecture reference:
  architecture.md §3.8, §5.4, §6.

  requirements.md FR-28.

  implementation_plan.md Phase 7:
    'Conflicts are detected, persisted via save_conflict(), and surfaced
    as review flags rather than auto-resolved.'

Normative policies: docs/adr/ADR-007 through ADR-016.

Phase 7 boundary — this service ONLY:
  - Reads validated Evidence via get_evidence_for_patient().
  - Delegates to ConflictDetectionTool.
  - Persists Conflict and ReviewFlag records.

NFR-9: logs contain only aggregate counts.
"""

from __future__ import annotations

import logging

from src.schemas.conflict import Conflict
from src.schemas.review_flag import ReviewFlag
from src.storage.storage_service import StorageService
from src.tools.conflict_detection_tool import ConflictDetectionTool

logger = logging.getLogger(__name__)


class ConflictDetectionService:
    """
    Conflict detection pipeline orchestration for Phase 7.

    Consumer: agent loop / executor (Phase 11).
    Citation: architecture.md §3.8; requirements.md FR-28;
              implementation_plan.md Phase 7.
    """

    def __init__(
        self,
        storage: StorageService,
        tool: ConflictDetectionTool | None = None,
    ) -> None:
        self._storage = storage
        self._tool = tool if tool is not None else ConflictDetectionTool()

    def detect_for_patient(
        self, patient_id: str
    ) -> tuple[list[Conflict], list[ReviewFlag]]:
        """
        Detect conflicts for a patient and persist results.

        Consumer: Executor when running ConflictDetectionTool (Phase 11).
        Citation: implementation_plan.md Phase 7 exit criteria.

        Storage reads:
          get_evidence_for_patient(patient_id)

        Storage writes:
          save_conflict() for each Conflict
          save_review_flag() for each ReviewFlag

        Parameters
        ----------
        patient_id:
            Owning Patient identifier.

        Returns
        -------
        tuple[list[Conflict], list[ReviewFlag]]
            Persisted Conflict and ReviewFlag records from this invocation.
        """
        evidence = self._storage.get_evidence_for_patient(patient_id)
        conflicts, flags = self._tool.detect(evidence)

        for conflict in conflicts:
            self._storage.save_conflict(conflict)
        for flag in flags:
            self._storage.save_review_flag(flag)

        logger.debug(
            "conflict_detection: processed %d evidence records, "
            "emitted %d conflicts, %d review flags",
            len(evidence),
            len(conflicts),
            len(flags),
        )

        return conflicts, flags
