"""Integration tests for Phases 7–13."""

from __future__ import annotations

from datetime import datetime, timezone

from src.agent.planner import GOAL_DETECT_CONFLICTS, Planner
from src.agent.wiring import build_agent_loop
from src.schemas.enums import EvidenceType, ReviewSeverity
from src.schemas.evidence import Evidence
from src.schemas.patient import Patient
from src.services.conflict_detection_service import ConflictDetectionService
from src.services.pending_results_service import PendingResultsService
from src.services.summary_generation_service import SummaryGenerationService
from src.storage.storage_service import StorageService
from src.tools.conflict_detection_tool import ConflictDetectionTool


def _sample_evidence(
    *,
    evidence_id: str,
    patient_id: str,
    field_name: str,
    field_value: str,
    evidence_type: EvidenceType = EvidenceType.DEMOGRAPHIC,
    page_number: int = 1,
) -> Evidence:
    text = f"Section: {field_value}"
    start = text.index(field_value)
    end = start + len(field_value)
    return Evidence(
        evidence_id=evidence_id,
        patient_id=patient_id,
        evidence_type=evidence_type,
        field_name=field_name,
        field_value=field_value,
        document_name="doc-a",
        page_number=page_number,
        source_text=text,
        source_start_char=start,
        source_end_char=end,
        section="Demographics",
        ocr_confidence=0.95,
        extraction_confidence=0.9,
        extraction_method="rule-based",
        status="validated",
    )


def test_phase7_conflict_detection() -> None:
    storage = StorageService()
    patient_id = "patient-7"
    storage.save_patient(
        Patient(
            patient_id=patient_id,
            patient_name=None,
            age=None,
            gender=None,
            documents=["doc-a"],
            created_at=datetime.now(timezone.utc),
        )
    )
    storage.save_evidence(
        _sample_evidence(
            evidence_id="e1",
            patient_id=patient_id,
            field_name="medication_dose",
            field_value="10mg",
        )
    )
    storage.save_evidence(
        _sample_evidence(
            evidence_id="e2",
            patient_id=patient_id,
            field_name="medication_dose",
            field_value="20mg",
            page_number=2,
        )
    )

    conflicts, flags = ConflictDetectionService(storage).detect_for_patient(
        patient_id
    )
    assert len(conflicts) == 1
    assert conflicts[0].field_name == "medication_dose"
    assert set(conflicts[0].conflicting_values) == {"10mg", "20mg"}
    assert len(flags) == 1
    assert flags[0].category == "conflict"
    assert flags[0].severity == ReviewSeverity.HIGH
    assert "Conflicting values detected for field" in flags[0].message


def test_phase7_tool_no_conflict_when_values_match() -> None:
    records = [
        _sample_evidence(
            evidence_id="e1",
            patient_id="p",
            field_name="allergy_substance",
            field_value="penicillin",
        ),
        _sample_evidence(
            evidence_id="e2",
            patient_id="p",
            field_name="allergy_substance",
            field_value="penicillin",
            page_number=2,
        ),
    ]
    conflicts, flags = ConflictDetectionTool().detect(records)
    assert conflicts == []
    assert flags == []


def test_phase8_pending_results() -> None:
    storage = StorageService()
    patient_id = "patient-8"
    storage.save_patient(
        Patient(
            patient_id=patient_id,
            patient_name=None,
            age=None,
            gender=None,
            documents=["doc-a"],
            created_at=datetime.now(timezone.utc),
        )
    )
    storage.save_evidence(
        _sample_evidence(
            evidence_id="p1",
            patient_id=patient_id,
            field_name="pending_result_description",
            field_value="CBC results pending",
            evidence_type=EvidenceType.PENDING_RESULT,
        )
    )

    flags = PendingResultsService(storage).detect_for_patient(patient_id)
    assert len(flags) == 1
    assert flags[0].category == "pending_result"
    assert flags[0].severity == ReviewSeverity.MEDIUM
    assert flags[0].message.startswith("Pending clinical result:")


def test_phase13_summary_generation() -> None:
    storage = StorageService()
    patient_id = "patient-13"
    storage.save_patient(
        Patient(
            patient_id=patient_id,
            patient_name=None,
            age=None,
            gender=None,
            documents=["doc-a"],
            created_at=datetime.now(timezone.utc),
        )
    )
    storage.save_evidence(
        _sample_evidence(
            evidence_id="d1",
            patient_id=patient_id,
            field_name="diagnosis_name",
            field_value="Type 2 diabetes",
            evidence_type=EvidenceType.DIAGNOSIS,
        )
    )

    summary = SummaryGenerationService(storage).generate_for_patient(patient_id)
    assert summary.patient_id == patient_id
    assert len(summary.diagnoses) == 1
    assert summary.diagnoses[0].field_value == "Type 2 diabetes"
    assert "d1" in summary.supporting_evidence_ids


def test_agent_loop_end_to_end() -> None:
    storage = StorageService()
    patient_id = "patient-loop"
    storage.save_patient(
        Patient(
            patient_id=patient_id,
            patient_name=None,
            age=None,
            gender=None,
            documents=["doc-a"],
            created_at=datetime.now(timezone.utc),
        )
    )
    storage.save_evidence(
        _sample_evidence(
            evidence_id="e1",
            patient_id=patient_id,
            field_name="diagnosis_name",
            field_value="Hypertension",
            evidence_type=EvidenceType.DIAGNOSIS,
        )
    )

    loop = build_agent_loop(storage, max_iterations=10)
    result = loop.run(patient_id)

    assert result.final_state.summary_ready or result.final_state.max_iterations_reached
    assert result.discharge_summary is not None
    assert len(result.trace) > 0
    assert GOAL_DETECT_CONFLICTS in result.final_state.completed_goals


def test_planner_completion_score_bounded() -> None:
    from src.schemas.agent_state import AgentState

    state = AgentState(
        patient_id="p",
        iteration=0,
        current_goal="",
        completed_goals=[],
        pending_goals=[],
        conflicts=[],
        review_flags=[],
        low_confidence_pages=[],
        evidence_count=5,
        completion_score=0.0,
        summary_ready=False,
        max_iterations_reached=False,
    )
    decision = Planner().plan(state)
    assert 0.0 <= decision.completion_score <= 1.0
