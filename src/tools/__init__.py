"""
Public API for src/tools.

Phase 4 delivers EvidenceExtractionTool.  Subsequent phases will add
EvidenceValidationTool and the agent-loop tools (Missing Data, Conflict
Detection, Medication Reconciliation, Pending Results, OCR Retry,
Review Flag) as each phase lands.

Architecture reference — architecture.md §6:
  'src/tools/ — OCR Tool, Evidence Extraction Tool, Evidence Validation
  Tool, plus the agent-loop tools.'
"""

from src.tools.evidence_extraction_tool import EvidenceExtractionTool

__all__ = [
    "EvidenceExtractionTool",
]
