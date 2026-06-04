"""
Public API for src/services.

Phase 4 delivers EvidenceExtractionService.  Subsequent phases will add
EvidenceValidationService, ConflictDetectionService, MedicationReconciliationService,
PendingResultsService, and SummaryGenerationService as each phase lands.

Architecture reference — architecture.md §6:
  'src/services/ — higher-level orchestrations that compose tools
  (extraction pipeline, validation pipeline, reconciliation, conflict
  detection, summary generation).'
"""

from src.services.evidence_extraction_service import EvidenceExtractionService

__all__ = [
    "EvidenceExtractionService",
]
