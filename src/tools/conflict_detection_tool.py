"""
ConflictDetectionTool — Phase 7: Conflict Detection (pure logic).

Architecture reference:
  architecture.md §3.8, §5.4:
    'Conflict Detection Tool — finds disagreements between evidence items
    referring to the same field; produces self-contained Conflict records.'
    'Disagreements ... are surfaced as Conflict records and as ReviewFlags.'

  requirements.md FR-28:
    'produces self-contained Conflict records when evidence items disagree.'

  implementation_plan.md Phase 7:
    'emits Conflict records together with ReviewFlag records.'

Normative policies: docs/adr/ADR-007 through ADR-016.

Phase 7 boundary — this tool ONLY:
  - Groups Evidence by field_name (ADR-007).
  - Detects distinct field_value disagreements.
  - Constructs Conflict and paired ReviewFlag records in memory.

This tool does NOT:
  - Read or write storage.
  - Mutate Evidence.
  - Normalize or resolve conflicts.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from src.schemas.conflict import Conflict
from src.schemas.enums import ReviewSeverity
from src.schemas.evidence import Evidence
from src.schemas.review_flag import ReviewFlag

_CONFLICT_MESSAGE_PREFIX = "Conflicting values detected for field"
_FLAG_CATEGORY_CONFLICT = "conflict"
_FLAG_STATUS_OPEN = "open"


class ConflictDetectionTool:
    """
    Pure conflict detection logic for Phase 7.

    Consumer: ConflictDetectionService (src/services/).
    Citation: architecture.md §3.8, §5.4; requirements.md FR-28;
              implementation_plan.md Phase 7; ADR-007–ADR-016.
    """

    def detect(self, evidence: list[Evidence]) -> tuple[list[Conflict], list[ReviewFlag]]:
        """
        Detect field-level disagreements across validated Evidence records.

        Consumer: ConflictDetectionService.detect_for_patient().
        Citation: ADR-007 (grouping), ADR-008 (cardinality), ADR-011 (ordering).

        Parameters
        ----------
        evidence:
            Validated Evidence in discovery order (caller supplies
            get_evidence_for_patient output).  Not modified.

        Returns
        -------
        tuple[list[Conflict], list[ReviewFlag]]
            Paired Conflict and ReviewFlag records for each qualifying group.
            Empty lists when no disagreements exist.
        """
        if not evidence:
            return [], []

        groups: dict[str, list[Evidence]] = defaultdict(list)
        for record in evidence:
            groups[record.field_name].append(record)

        conflicts: list[Conflict] = []
        flags: list[ReviewFlag] = []

        for field_name, records in groups.items():
            conflicting_values = _distinct_values_in_discovery_order(records)
            if len(conflicting_values) < 2:
                continue

            conflict = Conflict(
                conflict_id=str(uuid.uuid4()),
                patient_id=records[0].patient_id,
                field_name=field_name,
                conflicting_values=conflicting_values,
                evidence_ids=[record.evidence_id for record in records],
            )
            conflicts.append(conflict)
            flags.append(_build_conflict_review_flag(conflict, records))

        return conflicts, flags


def _distinct_values_in_discovery_order(records: list[Evidence]) -> list[str]:
    """Return distinct field_value strings in first-seen (discovery) order."""
    ordered: list[str] = []
    seen: set[str] = set()
    for record in records:
        if record.field_value not in seen:
            seen.add(record.field_value)
            ordered.append(record.field_value)
    return ordered


def _build_conflict_review_flag(
    conflict: Conflict, records: list[Evidence]
) -> ReviewFlag:
    """
    Build the ReviewFlag paired with a Conflict (ADR-008, ADR-016).

    related_page uses the first Evidence in discovery order (ADR-012).
    """
    values_clause = ", ".join(conflict.conflicting_values)
    message = (
        f"{_CONFLICT_MESSAGE_PREFIX} {conflict.field_name}: {values_clause}"
    )
    first_record = records[0]

    return ReviewFlag(
        flag_id=str(uuid.uuid4()),
        patient_id=conflict.patient_id,
        category=_FLAG_CATEGORY_CONFLICT,
        severity=ReviewSeverity.HIGH,
        message=message,
        evidence_ids=list(conflict.evidence_ids),
        related_page=first_record.page_number,
        created_at=datetime.now(timezone.utc),
        status=_FLAG_STATUS_OPEN,
    )
