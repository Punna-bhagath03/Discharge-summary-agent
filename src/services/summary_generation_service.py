"""
SummaryGenerationService — Phase 13: structured DischargeSummary composition.

Architecture reference:
  architecture.md §3.9, §3.10, §5.9:
    'Composes a DischargeSummary strictly from validated evidence in the
    Evidence Store.'

  requirements.md FR-38, FR-39, FR-40, FR-41.

  implementation_plan.md Phase 13:
    'strictly from validated evidence in the Evidence Store and active
    review flags.'

No OCR, no Page reads, no fabricated clinical content.
Prompt assets under src/prompts/ are reserved for future AI-assisted
wording; this service uses deterministic evidence-to-entry mapping to
satisfy no-hallucination requirements.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.schemas.discharge_summary import DischargeSummary, SummaryEntry
from src.schemas.enums import EvidenceType
from src.schemas.evidence import Evidence
from src.storage.storage_service import StorageService

logger = logging.getLogger(__name__)

_TYPE_TO_SECTION: dict[EvidenceType, str] = {
    EvidenceType.DIAGNOSIS: "diagnoses",
    EvidenceType.MEDICATION: "medications",
    EvidenceType.ALLERGY: "allergies",
    EvidenceType.FOLLOW_UP: "follow_up_instructions",
    EvidenceType.PENDING_RESULT: "pending_results",
}


class SummaryGenerationService:
    """
    Summary Generator for Phase 13.

    Consumer: Executor / AgentLoop when running SummaryGenerator tool.
    """

    def __init__(self, storage: StorageService) -> None:
        self._storage = storage

    def generate_for_patient(self, patient_id: str) -> DischargeSummary:
        """
        Build a DischargeSummary from validated Evidence and active flags.

        Storage reads:
          get_evidence_for_patient()
          get_review_flags_for_patient()

        Parameters
        ----------
        patient_id:
            Owning Patient identifier.

        Returns
        -------
        DischargeSummary
            Structured summary with per-entry provenance (SR-24).
        """
        evidence = self._storage.get_evidence_for_patient(patient_id)
        flag_ids = [
            flag.flag_id
            for flag in self._storage.get_review_flags_for_patient(patient_id)
        ]

        sections: dict[str, list[SummaryEntry]] = {
            "diagnoses": [],
            "medications": [],
            "allergies": [],
            "procedures": [],
            "pending_results": [],
            "follow_up_instructions": [],
        }

        supporting_ids: list[str] = []
        for record in evidence:
            supporting_ids.append(record.evidence_id)
            entry = _evidence_to_entry(record)
            section_key = _TYPE_TO_SECTION.get(record.evidence_type)
            if section_key is not None:
                sections[section_key].append(entry)

        if not supporting_ids:
            supporting_ids = []

        summary = DischargeSummary(
            patient_id=patient_id,
            diagnoses=sections["diagnoses"],
            medications=sections["medications"],
            allergies=sections["allergies"],
            procedures=sections["procedures"],
            pending_results=sections["pending_results"],
            follow_up_instructions=sections["follow_up_instructions"],
            review_flags=flag_ids,
            supporting_evidence_ids=supporting_ids,
            generated_at=datetime.now(timezone.utc),
        )

        logger.debug(
            "summary_generation: built summary with %d supporting evidence ids, "
            "%d review flags",
            len(supporting_ids),
            len(flag_ids),
        )

        return summary


def _evidence_to_entry(evidence: Evidence) -> SummaryEntry:
    """One SummaryEntry per Evidence record for individual traceability."""
    return SummaryEntry(
        field_name=evidence.field_name,
        field_value=evidence.field_value,
        supporting_evidence_ids=[evidence.evidence_id],
    )
