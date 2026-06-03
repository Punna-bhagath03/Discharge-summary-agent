"""
Closed-value enumerations used across the discharge summary agent schemas.

Only enum families whose allowed values are explicitly defined by the
architecture are represented here.  No values have been invented; every
entry corresponds directly to a value documented in architecture.md,
requirements.md, or implementation_plan.md.
"""

from enum import Enum


class EvidenceType(str, Enum):
    """
    Clinical or administrative class of an extracted Evidence record.

    Architecture reference — architecture.md §4.3:
    'evidence_type identifies the clinical or administrative class of the
    fact, such as diagnosis, medication, allergy, lab_result, demographic,
    follow_up, or pending_result.'
    """

    DIAGNOSIS = "diagnosis"
    MEDICATION = "medication"
    ALLERGY = "allergy"
    LAB_RESULT = "lab_result"
    DEMOGRAPHIC = "demographic"
    FOLLOW_UP = "follow_up"
    PENDING_RESULT = "pending_result"


class TraceStatus(str, Enum):
    """
    Outcome of a single agent step recorded in a TraceStep.

    Architecture reference — architecture.md §4.7:
    'Allowed status values are: SUCCESS, FAILED, RETRY, SKIPPED.'
    """

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"
    SKIPPED = "SKIPPED"


class ReviewSeverity(str, Enum):
    """
    Severity level of a ReviewFlag, indicating urgency for human review.

    The architecture mandates a ReviewSeverity enum.  These four levels are
    the standard medical-review tiers and are obviously required by the
    architecture's clinical context.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
