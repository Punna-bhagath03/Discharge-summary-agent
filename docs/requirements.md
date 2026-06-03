# Requirements

## 1. Purpose

This document specifies the functional and non-functional requirements
of the Discharge Summary Agent. The system ingests scanned patient
PDFs and produces an evidence-grounded, structured discharge summary
whose every fact can be traced back to the exact originating text span
in the source document.

## 2. Scope

In scope:

- Ingestion of scanned patient PDFs.
- OCR of PDF pages with stored page images, per-page
  `ocr_confidence`, and character offsets.
- Structured evidence extraction with exact-span provenance.
- Evidence Validation as a first-class gating component.
- Evidence Store persistence.
- Bounded agent loop with declared tools.
- Generation of a structured `DischargeSummary` and a full trace.

Out of scope:

- Direct integration with hospital information systems.
- Real-time streaming ingestion.
- Clinical decision-making beyond surfacing review flags.
- Full-document OCR retries (only targeted per-page retries are
  supported).

## 3. Functional Requirements

### 3.1 Ingestion
- **FR-1.** The system shall accept a scanned patient PDF as input.
- **FR-2.** The system shall register each upload against a `Patient`
  record identified by a stable `patient_id`.

### 3.2 OCR Tool
- **FR-3.** The OCR Tool shall produce per-page `raw_text`.
- **FR-4.** The OCR Tool shall record `ocr_confidence`, representing
  confidence in text recognition.
- **FR-4a.** The OCR Tool shall maintain `ocr_status` on each `Page`
  to track the OCR lifecycle.
- **FR-5.** The OCR Tool shall be invocable on individual pages so
  that the OCR Retry Tool can re-process only specific pages with low
  `ocr_confidence`.

### 3.3 Page Store
- **FR-6.** The Page Store shall persist `Page` records addressed by
  `(patient_id, document_name, page_number)`, with `page_image_path`
  available for OCR retry.
- **FR-7.** The Page Store shall be the only surface from which
  evidence is extracted and the only surface the OCR Retry Tool
  writes back to.
- **FR-8.** The OCR Retry Tool shall use the stored `page_image_path`
  from the `Page` record and shall not re-render the entire PDF.

### 3.4 Evidence Extraction Tool
- **FR-9.** The Evidence Extraction Tool shall read from the Page
  Store and emit `Evidence` records.
- **FR-10.** Every `Evidence` record shall carry an exact-span
  provenance triplet: `document_name`, `page_number`, `source_text`
  together with `source_start_char` and `source_end_char`.
- **FR-11.** The Evidence Extraction Tool shall not emit any record
  lacking the complete provenance set.
- **FR-12.** Every `Evidence` record shall carry both
  `ocr_confidence` (confidence in text recognition) and
  `extraction_confidence` (confidence in structured extraction).

### 3.5 Evidence Validation Tool
Evidence Validation is a first-class architectural component and is
the gate to the Evidence Store.

- **FR-13.** The Evidence Validation Tool shall reject records with
  missing required fields.
- **FR-14.** The Evidence Validation Tool shall reject records with
  invalid dates.
- **FR-15.** The Evidence Validation Tool shall detect and de-
  duplicate equivalent evidence.
- **FR-16.** The Evidence Validation Tool shall reject records with
  invalid `ocr_confidence` or `extraction_confidence` values.
- **FR-17.** The Evidence Validation Tool shall reject records with
  broken provenance references (missing or inconsistent
  `document_name`, `page_number`, `source_text`,
  `source_start_char`, or `source_end_char`).
- **FR-18.** The Evidence Validation Tool shall reject records where
  `source_start_char < 0`.
- **FR-19.** The Evidence Validation Tool shall reject records where
  `source_end_char <= source_start_char`.
- **FR-20.** The Evidence Validation Tool shall reject records where
  `source_end_char` exceeds the length of `source_text`.
- **FR-21.** The Evidence Validation Tool shall reject records with
  empty values where values are required.
- **FR-22.** The Evidence Validation Tool shall produce two outputs:
  validated `Evidence` (admitted to the Evidence Store) and
  `ReviewFlag` records describing rejected-but-clinically-relevant
  cases.

### 3.6 Evidence Store
- **FR-23.** The Evidence Store shall persist only validated
  `Evidence`.
- **FR-24.** The Evidence Store shall preserve the full provenance of
  every record.

### 3.7 Agent State
- **FR-25.** The Agent State shall be an explicit, inspectable object
  exposing at minimum: `patient_id`, `iteration`, `current_goal`,
  `completed_goals`, `pending_goals`, `conflicts`, `review_flags`,
  `low_confidence_pages`, `evidence_count`, `completion_score`,
  `summary_ready`, `max_iterations_reached`.
- **FR-26.** The planner shall determine readiness from
  `completion_score` (a graded numeric signal), not from a single
  boolean.

### 3.8 Agent Loop
The agent loop is bounded and operates only over Agent State and the
Evidence Store, acting through declared tools.

- **FR-27.** The agent shall provide a Missing Data Tool that
  identifies required fields without supporting evidence.
- **FR-28.** The agent shall provide a Conflict Detection Tool that
  produces self-contained `Conflict` records when evidence items
  disagree.
- **FR-29.** The agent shall provide a Medication Reconciliation Tool
  that consolidates medication evidence across documents while
  preserving every source reference.
- **FR-30.** The agent shall provide a Pending Results Tool that
  surfaces pending clinical results as review flags.
- **FR-31.** The agent shall provide an OCR Retry Tool that re-runs
  OCR only on pages listed in `AgentState.low_confidence_pages`, using
  the stored `page_image_path` for each page.
- **FR-32.** The agent shall provide a Review Flag Tool that emits
  `ReviewFlag` records referencing the underlying `Evidence` via
  `evidence_ids`.
- **FR-33.** The agent loop shall terminate when, and only when,
  `summary_ready == True` or `max_iterations_reached == True`.
- **FR-33a.** `max_iterations_reached` shall be derived from
  `AgentState.iteration` against a configurable
  `MAX_AGENT_ITERATIONS` limit.
- **FR-33b.** The planner shall not produce plans that can sustain
  infinite loops; the bounded termination conditions in FR-33 are the
  only permitted exits.
- **FR-33c.** Every iteration of the agent loop shall increment
  `AgentState.iteration` by exactly one.
- **FR-33d.** The executor shall be solely responsible for
  incrementing `AgentState.iteration`; no other component shall
  mutate that field.

### 3.9 Trace
- **FR-34.** Every planner decision, executor action, tool
  invocation, and state transition shall be recorded as a
  `TraceStep`.
- **FR-34a.** Every `TraceStep` shall include `trace_id`,
  `patient_id`, `goal`, `selected_tool`, `tool_input`, `tool_output`,
  `decision`, and `timestamp` in addition to `iteration` and
  `status`.
- **FR-35.** Every `TraceStep` shall include `iteration` so trace
  replay can be grouped by agent-loop iteration.
- **FR-36.** Every `TraceStep` shall include `status` with one of the
  following values: `SUCCESS`, `FAILED`, `RETRY`, or `SKIPPED`.
- **FR-37.** The trace shall be sufficient to reconstruct each fact
  in the final `DischargeSummary`.

### 3.10 Summary Generation
- **FR-38.** The Summary Generator shall produce a structured
  `DischargeSummary` strictly from validated evidence and active
  review flags.
- **FR-39.** The Summary Generator shall not call OCR, shall not read
  raw pages, and shall not introduce facts absent from the Evidence
  Store.
- **FR-40.** Every diagnosis, medication, pending result, and
  follow-up instruction in `DischargeSummary` shall be traceable to
  one or more entries in `supporting_evidence_ids`.

### 3.11 Output
- **FR-41.** The system shall emit a `DischargeSummary` object.
- **FR-42.** The system shall emit the associated `ReviewFlag` set.
- **FR-43.** The system shall emit the full `TraceStep` sequence.

## 4. Schema Requirements

All inter-component data shall conform to the following first-class
schemas: `Patient`, `Page`, `Evidence`, `Conflict`, `ReviewFlag`,
`AgentState`, `TraceStep`, `DischargeSummary`.

### 4.1 `Patient`
- **SR-1.** `Patient` records shall include:
  `patient_id`, `patient_name`, `age`, `gender`, `documents`,
  `created_at`.
- **SR-2.** `patient_name`, `age`, and `gender` shall be optional
  (`None` is permitted when unknown) and shall never be fabricated.
- **SR-3.** `documents` shall be the list of document names ingested
  for the patient.
- **SR-4.** All other artifacts (`Page`, `Evidence`, `Conflict`,
  `ReviewFlag`, `AgentState`, `TraceStep`, `DischargeSummary`) shall
  reference a `Patient` via `patient_id`.

### 4.2 `Page`
- **SR-5.** `Page` records shall include:
  `patient_id`, `document_name`, `page_number`, `page_image_path`,
  `raw_text`, `ocr_status`, `ocr_confidence`.
- **SR-6.** `patient_id` shall reference the owning `Patient`
  record, and `(document_name, page_number)` shall address the page
  within that patient.
- **SR-6a.** `page_image_path` shall point to the stored image used
  for page-level OCR retry.
- **SR-6b.** `ocr_status` shall track the OCR lifecycle of the page.

### 4.3 `Evidence`
- **SR-7.** `Evidence` records shall include:
  `evidence_id`, `patient_id`, `evidence_type`, `field_name`, `field_value`,
  `document_name`, `page_number`, `source_text`,
  `source_start_char`, `source_end_char`, `section`,
  `ocr_confidence`, `extraction_confidence`, `extraction_method`,
  `status`.
- **SR-7a.** `Evidence.patient_id` shall reference the owning `Patient`
  record, consistent with SR-4.
- **SR-8.** `Evidence` records without a complete exact-span
  provenance set shall be rejected by Evidence Validation.
- **SR-9.** `ocr_confidence` shall represent confidence in text
  recognition. `extraction_confidence` shall represent confidence in
  structured extraction.
- **SR-10.** `evidence_type` shall identify the kind of evidence,
  such as `diagnosis`, `medication`, `allergy`, `lab_result`,
  `demographic`, `follow_up`, or `pending_result`. `field_name` shall
  identify the specific field being extracted, and `field_value`
  shall contain the extracted value. Example:
  `evidence_type = medication`, `field_name = medication_name`,
  `field_value = metformin`.

### 4.4 `Conflict`
- **SR-11.** `Conflict` records shall include:
  `conflict_id`, `patient_id`, `field_name`, `conflicting_values`,
  `evidence_ids`.
- **SR-11a.** `conflict_id` shall uniquely identify the Conflict record,
  making it individually addressable consistent with every other
  first-class artifact.
- **SR-11b.** `Conflict.patient_id` shall reference the owning `Patient`
  record, consistent with SR-4.
- **SR-12.** `conflicting_values` shall be a list of the values in
  disagreement, and `evidence_ids` shall be a list of the evidence
  records supporting those values.
- **SR-13.** `Conflict` records shall be self-contained and auditable
  without re-querying the Evidence Store.

### 4.5 `ReviewFlag`
- **SR-14.** `ReviewFlag` records shall include:
  `flag_id`, `patient_id`, `category`, `severity`, `message`,
  `evidence_ids`, `related_page`, `created_at`, `status`.
- **SR-14a.** `ReviewFlag.patient_id` shall reference the owning `Patient`
  record, consistent with SR-4.
- **SR-15.** `ReviewFlag` records shall always reference the
  underlying `Evidence` via `evidence_ids`. Free-floating review
  flags are not permitted.

### 4.6 `AgentState`
- **SR-16.** `AgentState` shall include:
  `patient_id`, `iteration`, `current_goal`, `completed_goals`,
  `pending_goals`, `conflicts`, `review_flags`,
  `low_confidence_pages`, `evidence_count`, `completion_score`,
  `summary_ready`, `max_iterations_reached`.
- **SR-17.** `AgentState.patient_id` shall reference the `Patient`
  record.
- **SR-18.** The OCR Retry Tool shall read `low_confidence_pages`
  directly from `AgentState` instead of rescanning all pages.

### 4.7 `TraceStep`
- **SR-19.** `TraceStep` records shall include:
  `trace_id`, `patient_id`, `iteration`, `goal`, `selected_tool`,
  `tool_input`, `tool_output`, `decision`, `status`, `timestamp`.
- **SR-19a.** `trace_id` shall uniquely identify a step, and
  `patient_id` shall reference the owning `Patient` record.
- **SR-19b.** `selected_tool`, `tool_input`, and `tool_output` shall
  capture, respectively, the tool chosen, the exact data passed to
  it, and the exact data it produced.
- **SR-19c.** `goal` shall record the active goal at the time of the
  step, and `decision` shall record the planner or executor decision
  that led to or resulted from the step.
- **SR-19d.** `timestamp` shall record when the step occurred.
- **SR-20.** `iteration` shall support replay grouped by agent-loop
  iteration.
- **SR-21.** Allowed `TraceStep.status` values are `SUCCESS`,
  `FAILED`, `RETRY`, and `SKIPPED`.

### 4.8 `DischargeSummary`
- **SR-22.** `DischargeSummary` shall include:
  `patient_id`, `diagnoses`, `medications`, `allergies`,
  `procedures`, `pending_results`, `follow_up_instructions`,
  `review_flags`, `supporting_evidence_ids`, `generated_at`.
- **SR-23.** `diagnoses`, `medications`, `allergies`, `procedures`,
  `pending_results`, and `follow_up_instructions` shall be lists of
  structured entries; `review_flags` shall be a list of review flag
  identifiers.
- **SR-24.** Each entry in `diagnoses`, `medications`, `allergies`,
  `procedures`, `pending_results`, and `follow_up_instructions` shall
  be traceable through `supporting_evidence_ids` to one or more
  `Evidence` records, each of which carries its own exact-span
  provenance.

## 5. Non-Functional Requirements

### 5.1 Provenance and Auditability
- **NFR-1.** Every fact in any output shall be traceable to a
  specific `(document_name, page_number)` and an exact character
  range `(source_start_char, source_end_char)` within `source_text`.
- **NFR-2.** Every agent decision shall be inspectable through the
  trace.

### 5.2 Reliability
- **NFR-3.** The pipeline shall fail safely: when evidence is
  insufficient the system shall surface review flags rather than
  fabricate content.
- **NFR-4.** The agent loop shall be bounded by both
  `completion_score`-driven readiness and `max_iterations_reached`,
  with `max_iterations_reached` derived from a configurable
  `MAX_AGENT_ITERATIONS` limit. Infinite loops shall not be
  reachable from any planner output.

### 5.3 Maintainability
- **NFR-5.** Each architectural component shall be independently
  testable.
- **NFR-6.** Inter-component contracts shall be defined exclusively
  by the schemas listed in §4.

### 5.4 Extensibility
- **NFR-7.** New agent tools shall be addable without modifying the
  planner/executor control flow.
- **NFR-8.** Storage backends shall be replaceable without changing
  upstream or downstream stages.

### 5.5 Security and Privacy
- **NFR-9.** Patient data shall not leak into logs or traces in
  unprotected form.
- **NFR-10.** Secrets shall be supplied via environment variables and
  shall not be committed to the repository.

## 6. Constraints

- Python 3.12 runtime.
- `src/`-based project layout.
- Evidence-based extraction with exact-span provenance is mandatory.
- No hallucinated content is permitted under any circumstance.
- OCR retries are restricted to per-page scope and must use
  `page_image_path` from the stored `Page` record.

## 7. Assumptions

- Input PDFs may be of varying quality, including low-resolution
  scans.
- Multiple documents may describe the same patient encounter and may
  contain conflicting information.
- Some clinical results may be marked as pending in the source.

## 8. Acceptance Criteria

The system is considered to meet its requirements when:

- Every fact in a generated `DischargeSummary` can be traced to a
  specific `(document_name, page_number)` and an exact character
  range within the corresponding `source_text`.
- A reviewer can move from `DischargeSummary` to
  `supporting_evidence_ids`, then to `Evidence`, then to `source_text`,
  then to the source character span, and finally to the originating
  page.
- Evidence Validation rejects malformed, duplicate, or
  provenance-broken records and emits review flags where appropriate.
- Evidence Validation rejects records where `source_start_char < 0`,
  `source_end_char <= source_start_char`, or `source_end_char` exceeds
  the length of `source_text`.
- Conflicts and pending results are surfaced as `ReviewFlag` records
  rather than silently resolved.
- The planner's readiness decision is driven by `completion_score`
  and the loop terminates only when `summary_ready == True` or
  `max_iterations_reached == True`, with `AgentState.iteration`
  incremented by the executor on every iteration.
- The `TraceStep` sequence allows a reviewer to reconstruct each
  agent decision and each fact in the summary, with every trace step
  grouped by `iteration` and marked as `SUCCESS`, `FAILED`, `RETRY`,
  or `SKIPPED`.
- No `DischargeSummary` contains information absent from the
  Evidence Store.
