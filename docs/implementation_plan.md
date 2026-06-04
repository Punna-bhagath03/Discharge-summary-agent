# Implementation Plan

## 1. Purpose

This document describes the phased implementation plan for the
Discharge Summary Agent. Each phase delivers a self-contained
capability of the architecture and is intended to be implemented,
reviewed, and tested in isolation before the next phase begins. The
plan is aligned 1:1 with the components and schemas defined in
`architecture.md` and the contracts defined in `requirements.md`.

## 2. Guiding Principles

- Implement strictly along architectural boundaries.
- Do not anticipate features beyond the documented architecture.
- Every phase must produce inspectable artifacts (schemas, stored
  data, or trace entries).
- Evidence-based extraction, exact-span provenance, and
  no-hallucination rules apply from the first phase onward.

## 3. Phase Overview

| #  | Phase                          | Primary Module(s)               |
|----|--------------------------------|---------------------------------|
| 1  | Schemas                        | `src/schemas/`                  |
| 2  | Storage Layer                  | `src/storage/`                  |
| 3  | OCR Layer                      | `src/tools/`                    |
| 4  | Evidence Extraction            | `src/tools/`, `src/services/`   |
| 5  | Evidence Validation            | `src/tools/`, `src/services/`   |
| 6  | Medication Reconciliation      | `src/tools/`, `src/services/`   |
| 7  | Conflict Detection             | `src/tools/`, `src/services/`   |
| 8  | Pending Results Detection      | `src/tools/`, `src/services/`   |
| 9  | Agent State Management         | `src/agent/`                    |
| 10 | Planner                        | `src/agent/`                    |
| 11 | Executor                       | `src/agent/`                    |
| 12 | Trace System                   | `src/agent/`                    |
| 13 | Summary Generation             | `src/services/`, `src/prompts/` |

## 4. Phase Details

### Phase 1 — Schemas

Define the first-class data contracts used across the system. All
inter-component data must conform to these schemas. Schemas to be
defined:

- `Patient`
- `Page`
- `Evidence`
- `Conflict`
- `ReviewFlag`
- `TraceStep`
- `AgentState`
- `DischargeSummary`

`Patient` is the first-class anchor for the system and must include
`patient_id`, `patient_name`, `age`, `gender`, `documents`, and
`created_at`. `patient_name`, `age`, and `gender` are optional
(`None` is permitted when unknown) and must never be fabricated.
`documents` is the list of document names ingested for the patient.
All other artifacts (`Page`, `Evidence`, `Conflict`, `ReviewFlag`,
`AgentState`, `TraceStep`, `DischargeSummary`) reference a `Patient`
via `patient_id`.

`Page` must include `patient_id` (referencing the `Patient` record),
`document_name`, `page_number`, `page_image_path`, `raw_text`,
`ocr_status`, and `ocr_confidence`. `(patient_id, document_name,
page_number)` addresses a page within the system. `page_image_path`
allows OCR retry to operate on the stored image for an individual
page instead of re-rendering the full PDF. `raw_text` is the
recognized text that `Evidence` is extracted from, with spans
`(source_start_char, source_end_char)` indexing into it.
`ocr_status` tracks the OCR lifecycle of the page, and
`ocr_confidence` drives `AgentState.low_confidence_pages`.

`Evidence` must support the full exact-span provenance set
(`document_name`, `page_number`, `source_text`,
`source_start_char`, `source_end_char`) alongside `evidence_id`,
`patient_id` (referencing the `Patient` record), `evidence_type`,
`field_name`, `field_value`, `section`, `ocr_confidence`,
`extraction_confidence`, `extraction_method`, and `status`.
`ocr_confidence` represents confidence in text recognition;
`extraction_confidence` represents confidence in structured
extraction. `evidence_type` identifies the kind of evidence, such as
`diagnosis`, `medication`, `allergy`, `lab_result`, `demographic`,
`follow_up`, or `pending_result`; `field_name` identifies the specific
field; `field_value` contains the extracted value. Example:
`evidence_type = medication`, `field_name = medication_name`,
`field_value = metformin`.

`Conflict` must include `conflict_id` (unique identifier),
`patient_id` (referencing the `Patient` record), `field_name`,
`conflicting_values`, and `evidence_ids`. It must be self-contained
and auditable without re-querying the Evidence Store.

`ReviewFlag` must reference `Evidence` via `evidence_ids` and include
`flag_id`, `patient_id` (referencing the `Patient` record), `category`,
`severity`, `message`, `related_page`, `created_at`, and `status`.

`AgentState` must include `patient_id` (referencing the `Patient`
record), `iteration`, `current_goal`, `completed_goals`,
`pending_goals`, `conflicts`, `review_flags`, `low_confidence_pages`,
`evidence_count`, `completion_score`, `summary_ready`, and
`max_iterations_reached`.

`TraceStep` must include `trace_id`, `patient_id` (referencing the
`Patient` record), `iteration`, `goal`, `selected_tool`,
`tool_input`, `tool_output`, `decision`, `status`, and `timestamp`.
Allowed `status` values are `SUCCESS`, `FAILED`, `RETRY`, and
`SKIPPED`.

`DischargeSummary` must include `patient_id` (referencing the
`Patient` record), `diagnoses`, `medications`, `allergies`,
`procedures`, `pending_results`, `follow_up_instructions`,
`review_flags`, `supporting_evidence_ids`, and `generated_at`. Every
entry in `diagnoses`, `medications`, `allergies`, `procedures`,
`pending_results`, and `follow_up_instructions` must be traceable to
supporting evidence IDs.

**Exit criteria:** All inter-stage data is described by an explicit
schema.

### Phase 2 — Storage Layer

Implement persistence for pages, evidence, traces, review flags, and
conflicts, plus patient-level loaders. The storage layer is the only
component permitted to write to or read from durable storage; every
other component goes through it.

Required operations:

- `save_patient()`
- `get_patient()`
- `save_page()`
- `save_evidence()`
- `save_trace()`
- `save_review_flag()`
- `save_conflict()`
- `get_conflicts_for_patient()`

All operations must preserve the full provenance carried by their
inputs. `save_evidence()` is the only path into the Evidence Store
and must reject records that have not been admitted by Evidence
Validation (Phase 5).

**Exit criteria:** Pages, validated evidence, traces, review flags,
and conflicts can be persisted and loaded for a given `patient_id`
with provenance intact.

### Phase 3 — OCR Layer

Implement the OCR Tool. The tool produces per-page `raw_text`
together with `ocr_status`, `ocr_confidence`, `page_image_path`, and
the character offsets required for exact-span provenance. It
supports invocation on individual pages so that the OCR Retry Tool
(Phase 11) can re-process specific pages with low `ocr_confidence`
only, using the stored page image rather than re-rendering the
entire PDF.

**Exit criteria:** Given a PDF, the OCR layer produces per-page
output suitable for ingestion into the Page Store; targeted per-page
re-OCR is supported.

### Phase 4 — Evidence Extraction

Implement the Evidence Extraction Tool. It reads pages from the Page
Store and emits `Evidence` records, each carrying a complete
exact-span provenance triplet
(`document_name`, `page_number`, `source_text`,
`source_start_char`, `source_end_char`).

**Exit criteria:** `Evidence` records are produced from the Page
Store with full exact-span provenance; no record is emitted without
it.

### Phase 5 — Evidence Validation Service

Implement Evidence Validation as a first-class service and the gate
to the Evidence Store.

**Responsibilities:**

- Detect missing fields.
- Detect invalid dates.
- Detect duplicate evidence.
- Detect invalid `ocr_confidence` or `extraction_confidence` values.
- Detect broken provenance references.
- Detect `source_start_char < 0`.
- Detect `source_end_char <= source_start_char`.
- Detect `source_end_char` values that exceed the length of
  `source_text`.
- Detect empty values where values are required.

**Outputs:**

- **Validated Evidence** — admitted to the Evidence Store via
  `save_evidence()`.
- **Review Flags** — produced for rejected-but-clinically-relevant
  records, persisted via `save_review_flag()`, and always referencing
  the underlying evidence via `evidence_ids`, with `created_at`
  recorded.

**Exit criteria:** Only validated evidence reaches the Evidence
Store; rejected records are either dropped or surfaced as review
flags with a clear `category`, `severity`, and provenance reference.

### Phase 6 — Medication Reconciliation

Implement the Medication Reconciliation Tool. It consolidates
medication evidence across documents and preserves every source
reference. Conflicting entries are not silently merged; they are
forwarded to Phase 7.

**Exit criteria:** A reconciled medication view is produced from
validated evidence, with provenance preserved for every entry.

### Phase 7 — Conflict Detection

Implement the Conflict Detection Tool. It identifies disagreements
between evidence items referring to the same field and emits
`Conflict` records together with `ReviewFlag` records. Each
`Conflict` record includes `field_name`, `conflicting_values`, and
`evidence_ids` so it remains self-contained and auditable.

**Exit criteria:** Conflicts are detected, persisted via
`save_conflict()`, and surfaced as review flags rather than
auto-resolved.

### Phase 8 — Pending Results Detection

Implement the Pending Results Tool. It identifies clinical results
marked as pending in the source and emits review flags that reference
the underlying evidence.

**Exit criteria:** Pending results are reliably identified from
validated evidence and surfaced as review flags.

### Phase 9 — Agent State Management

Implement the `AgentState` container the agent loop operates on,
exposing `patient_id`, `iteration`, `current_goal`,
`completed_goals`, `pending_goals`, `conflicts`, `review_flags`,
`low_confidence_pages`, `evidence_count`, `completion_score`,
`summary_ready`, and `max_iterations_reached`.

State transitions must be explicit and inspectable; every transition
must be writable to the trace by the executor (Phase 11) and trace
system (Phase 12).

**Exit criteria:** The agent has a single well-defined state object
exposing all fields above, with `completion_score` computed from the
state and `low_confidence_pages` available for targeted OCR retry.

### Phase 10 — Planner

Implement the planner. Given an `AgentState`, the planner produces
the next action — for example: run the Missing Data Tool, run the
Conflict Detection Tool, run the Medication Reconciliation Tool, run
the Pending Results Tool, invoke the OCR Retry Tool on specific
pages listed in `AgentState.low_confidence_pages`, emit a review flag,
or proceed to summary generation. The planner does not execute
actions.

Readiness for summary generation is decided from `completion_score`,
not from a boolean.

**Exit criteria:** Given an `AgentState`, the planner produces a
deterministic next action and a readiness assessment driven by
`completion_score`.

### Phase 11 — Executor

Implement the executor. The executor carries out the action selected
by the planner by invoking the corresponding tool, applies the
resulting changes to `AgentState` through declared transitions, and
hands every step to the trace system. The executor is the only
component permitted to mutate `AgentState`, and is solely responsible
for incrementing `AgentState.iteration` by exactly one on every
agent-loop iteration. The agent loop terminates only when
`summary_ready == True` or `max_iterations_reached == True`, where
`max_iterations_reached` is derived from `AgentState.iteration`
against the configurable `MAX_AGENT_ITERATIONS` limit.

**Exit criteria:** Planner-selected actions are executed, state
transitions are recorded, `AgentState.iteration` is incremented by
the executor on every iteration, the loop terminates only on the
two declared conditions, and tool outputs (evidence, conflicts,
review flags) reach the storage layer.

### Phase 12 — Trace System

Implement the trace system. Every planner decision, executor action,
tool invocation, state transition, and produced artifact is recorded
as a `TraceStep` via `save_trace()`. Every `TraceStep` includes
`trace_id`, `patient_id`, `iteration`, `goal`, `selected_tool`,
`tool_input`, `tool_output`, `decision`, `timestamp`, and a `status`
value of `SUCCESS`, `FAILED`, `RETRY`, or `SKIPPED`. The trace must
be sufficient to reconstruct the agent's behavior end to end and
replay it grouped by iteration.

**Exit criteria:** Every agent decision is captured in the trace and
the resulting `TraceStep` sequence supports full replay for audit.

### Phase 13 — Summary Generation

Implement the Summary Generator. It composes a structured
`DischargeSummary` strictly from validated evidence in the Evidence
Store and active review flags. It consumes prompt assets from
`src/prompts/` and produces a `DischargeSummary` object containing
`patient_id`, `diagnoses`, `medications`, `allergies`, `procedures`,
`pending_results`, `follow_up_instructions`, `review_flags`,
`supporting_evidence_ids`, and `generated_at`.

The generator does not call OCR, does not read raw pages, and does
not introduce facts that are not represented in the Evidence Store.
Every entry in `diagnoses`, `medications`, `allergies`, `procedures`,
`pending_results`, and `follow_up_instructions` must be derivable
from one or more entries in `supporting_evidence_ids`, each resolving
to an `Evidence` record carrying exact-span provenance.

**Exit criteria:** A `DischargeSummary` is produced from validated
evidence only, with full provenance, an attached review flag set, and
a complete trace.

## 5. Sequencing and Dependencies

- Phase 1 (Schemas) is foundational and must be completed first.
- Phase 2 (Storage) depends on Phase 1.
- Phase 3 (OCR) depends on Phase 2 (writes pages via the Page
  Store).
- Phase 4 (Extraction) depends on Phases 2 and 3.
- Phase 5 (Validation) depends on Phase 4 and is the gate to the
  Evidence Store.
- Phases 6–8 (Reconciliation, Conflict Detection, Pending Results)
  depend on a populated Evidence Store (Phase 5).
- Phases 9–12 (State, Planner, Executor, Trace) depend on Phases 6–8
  to have meaningful state and actions to plan over.
- Phase 13 (Summary) depends on all previous phases.

## 6. Definition of Done (per phase)

A phase is considered complete only when:

- The relevant module is implemented behind the interfaces declared
  in Phase 1.
- Behavior is covered by tests in `tests/`.
- The phase does not introduce features outside the architecture.
- No code path can produce facts without exact-span provenance.
- All artifacts produced by the phase are persisted via the storage
  layer's declared operations.
