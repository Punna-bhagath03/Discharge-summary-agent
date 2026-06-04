"""
PendingResultsTool — Phase 8: Pending Results Detection (pure logic).

Architecture reference:
  architecture.md §3.8:
    'Pending Results Tool — identifies clinical results marked as pending
    in the source and surfaces them as review flags.'

  requirements.md FR-30:
    'surfaces pending clinical results as review flags.'

  implementation_plan.md Phase 8:
    'Pending results are reliably identified from validated evidence and
    surfaced as review flags.'

Normative policy: docs/adr/ADR-017.md.

Phase 8 boundary — this tool ONLY:
  - Builds ReviewFlag records from PENDING_RESULT Evidence.
  - Does not create Conflict records.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.schemas.enums import ReviewSeverity
from src.schemas.evidence import Evidence
from src.schemas.review_flag import ReviewFlag

_MESSAGE_PREFIX = "Pending clinical result:"
_FLAG_CATEGORY = "pending_result"
_FLAG_STATUS_OPEN = "open"


class PendingResultsTool:
    """
    Pure pending-results detection for Phase 8.

    Consumer: PendingResultsService.
    Citation: requirements.md FR-30; ADR-017.
    """

    def detect(self, pending_evidence: list[Evidence]) -> list[ReviewFlag]:
        """
        Build one ReviewFlag per pending-result Evidence record.

        Consumer: PendingResultsService.detect_for_patient().
        Citation: ADR-017.

        Parameters
        ----------
        pending_evidence:
            Evidence with evidence_type PENDING_RESULT, discovery order.
            Not modified.

        Returns
        -------
        list[ReviewFlag]
            One flag per input record.  Empty when input is empty.
        """
        flags: list[ReviewFlag] = []
        for record in pending_evidence:
            flags.append(
                ReviewFlag(
                    flag_id=str(uuid.uuid4()),
                    patient_id=record.patient_id,
                    category=_FLAG_CATEGORY,
                    severity=ReviewSeverity.MEDIUM,
                    message=f"{_MESSAGE_PREFIX} {record.field_value}",
                    evidence_ids=[record.evidence_id],
                    related_page=record.page_number,
                    created_at=datetime.now(timezone.utc),
                    status=_FLAG_STATUS_OPEN,
                )
            )
        return flags
