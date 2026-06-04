"""
Public API for src/services.

Phase 4 delivers EvidenceExtractionService.  Phase 5 delivers
EvidenceValidationService.  Subsequent phases will add
MedicationReconciliationService, ConflictDetectionService,
PendingResultsService, and SummaryGenerationService as each phase lands.

Architecture reference — architecture.md §6:
  'src/services/ — higher-level orchestrations that compose tools
  (extraction pipeline, validation pipeline, reconciliation, conflict
  detection, summary generation).'
"""

from src.services.evidence_extraction_service import EvidenceExtractionService
from src.services.evidence_validation_service import EvidenceValidationService

__all__ = [
    "EvidenceExtractionService",
    "EvidenceValidationService",
]
