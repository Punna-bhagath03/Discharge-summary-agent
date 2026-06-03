"""
Public API for src/schemas.

All schema classes and enumerations used as inter-component contracts across
the discharge summary agent pipeline are exported from this module.  Importing
from src.schemas (rather than from individual submodules) is the intended
pattern for all other phases of the project.
"""

from src.schemas.agent_state import AgentState
from src.schemas.conflict import Conflict
from src.schemas.discharge_summary import DischargeSummary, SummaryEntry
from src.schemas.enums import EvidenceType, ReviewSeverity, TraceStatus
from src.schemas.evidence import Evidence
from src.schemas.page import Page
from src.schemas.patient import Patient
from src.schemas.review_flag import ReviewFlag
from src.schemas.trace_step import TraceStep

__all__ = [
    # Enumerations
    "EvidenceType",
    "ReviewSeverity",
    "TraceStatus",
    # Core schemas — ordered by pipeline stage
    "Patient",
    "Page",
    "Evidence",
    "Conflict",
    "ReviewFlag",
    "AgentState",
    "TraceStep",
    "DischargeSummary",
    # Supporting types
    "SummaryEntry",
]
