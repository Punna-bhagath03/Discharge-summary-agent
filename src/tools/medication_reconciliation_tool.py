"""
MedicationReconciliationTool — Phase 6: Medication Reconciliation (pure logic).

Architecture reference:
  architecture.md §3.8:
    'Medication Reconciliation Tool — consolidates medication evidence
    across documents while preserving every source reference.'

  requirements.md FR-29:
    'The agent shall provide a Medication Reconciliation Tool that
    consolidates medication evidence across documents while preserving
    every source reference.'

  implementation_plan.md Phase 6:
    'Implement the Medication Reconciliation Tool.  It consolidates
    medication evidence across documents and preserves every source
    reference.  Conflicting entries are not silently merged; they are
    forwarded to Phase 7.'

This module contains only the per-record grouping and forwarding logic.
It is pure: no storage reads, no storage writes, no persistence, no new
schema, and no normalization.

Phase 6 boundary — this tool ONLY:
  - Groups medication Evidence records by field_name.
  - Identifies groups that have exactly one evidence record per
    field_name across all documents (consolidated groups).
  - Identifies groups that have more than one distinct field_value for
    the same field_name (disagreement candidates forwarded to Phase 7).

This tool does NOT:
  - Normalize medication names, dosage, route, or frequency.
  - Choose a canonical medication record.
  - Remove provenance records.
  - Create Conflict records (Phase 7).
  - Create ReviewFlag records (Phase 7/8).
  - Call save_conflict(), save_review_flag(), save_trace(),
    save_evidence(), or save_page().
  - Mutate AgentState.

Architecture-gap note — medication equivalence:
  The documents do not define medication equivalence criteria, conflict
  criteria, or the Phase 6 → Phase 7 handoff object (see design audit).
  This tool uses the narrowest safe interpretation: same field_name with
  more than one distinct field_value (exact string comparison, no
  normalization) signals a disagreement candidate.  No medication
  equivalence is invented.

Architecture-gap note — output contract:
  No new schema is defined.  The public output of this tool is a list of
  existing Evidence records only.  Disagreement candidates remain internal
  grouping details because the architecture does not define a Phase 6 →
  Phase 7 handoff contract.

NFR-9: this module logs nothing.  It receives Evidence objects and
returns Evidence objects; no patient-linked values are handled in logs.
"""

from src.schemas.evidence import Evidence


class MedicationReconciliationTool:
    """
    Pure medication reconciliation logic for Phase 6.

    Consumer: MedicationReconciliationService (src/services/).
    Citation: architecture.md §3.8; requirements.md FR-29;
              implementation_plan.md Phase 6.

    Groups validated medication Evidence by field_name (exact string, no
    normalization) and keeps every original Evidence record in the returned
    reconciled view.  Groups with more than one distinct field_value are kept
    as internal disagreement candidates, but no separate public contract is
    returned because NFR-6 permits only architecture-defined schemas.

    No Evidence object is modified.  No new schema is constructed.
    """

    def reconcile(self, medication_evidence: list[Evidence]) -> list[Evidence]:
        """
        Return the reconciled medication view as existing Evidence records.

        Consumer: MedicationReconciliationService.reconcile_for_patient().
        Citation:
            requirements.md FR-29:
                'consolidates medication evidence across documents while
                preserving every source reference.'
            implementation_plan.md Phase 6:
                'Conflicting entries are not silently merged; they are
                forwarded to Phase 7.'
            architecture.md §5.2:
                'No component may fabricate, default, or infer a value
                that is not present in the source.' — no normalization.

        Parameters
        ----------
        medication_evidence:
            Validated Evidence records with evidence_type == MEDICATION.
            Not modified.  Caller is responsible for pre-filtering.

        Returns
        -------
        list[Evidence]
            Existing Evidence records only.  Records from consolidated groups
            are returned first, followed by records from disagreement-candidate
            groups.  No Conflict objects, ReviewFlag objects, or custom result
            contracts are created.
        """
        consolidated, disagreement_candidates = self._partition(
            medication_evidence
        )
        return [*consolidated, *disagreement_candidates]

    def _partition(
        self, medication_evidence: list[Evidence]
    ) -> tuple[list[Evidence], list[Evidence]]:
        """
        Internal grouping helper.

        This is not an inter-component contract.  It exists only so the
        service can preserve aggregate logging while public outputs remain
        limited to architecture-defined Evidence records (NFR-6).
        """
        # Group by field_name (exact string, no normalization — §5.2).
        groups: dict[str, list[Evidence]] = {}
        for ev in medication_evidence:
            groups.setdefault(ev.field_name, []).append(ev)

        consolidated: list[Evidence] = []
        disagreement_candidates: list[Evidence] = []

        for field_name_key, records in groups.items():
            distinct_values: set[str] = {ev.field_value for ev in records}

            if len(distinct_values) == 1:
                # All records agree on the field_value — include all,
                # preserving every source reference (FR-29).
                consolidated.extend(records)
            else:
                # More than one distinct field_value for the same
                # field_name — disagreement candidate, forwarded to
                # Phase 7 as underlying Evidence (implementation_plan.md
                # Phase 6: "forwarded to Phase 7").
                disagreement_candidates.extend(records)

        return consolidated, disagreement_candidates
