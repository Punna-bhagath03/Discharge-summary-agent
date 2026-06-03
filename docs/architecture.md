# Architecture

## 1. Overview

The Discharge Summary Agent is an evidence-grounded AI system that
ingests scanned patient PDFs and produces a structured discharge
summary. It is engineered for production review in clinical contexts,
where every emitted fact must be auditable, every agent decision must
be traceable, and missing information must never be substituted by
inference.

The system is organized as a deterministic pipeline whose final stage
is a bounded, tool-using agent loop. The agent never reads the raw PDF
and never invokes OCR ad hoc — it operates exclusively over validated
evidence and acts through a small, well-defined set of tools.

## 2. End-to-End Pipeline

```
PDF Upload
   │
   ▼
OCR Tool
   │
   ▼
Page Store
   │
   ▼
Evidence Extraction Tool
   │
   ▼
Evidence Validation Tool
   │
   ▼
Evidence Store
   │
   ▼
Agent State
   │
   ▼
Agent Loop
   ├── Missing Data Tool
   ├── Conflict Detection Tool
   ├── Medication Reconciliation Tool
   ├── Pending Results Tool
   ├── OCR Retry Tool
   └── Review Flag Tool
   │
   ▼
Summary Generator
   │
   ▼
Structured Draft (DischargeSummary)
   │
   ▼
Trace Output
```

Each arrow is a one-way, contract-bound transition. No downstream
component may bypass the stage above it, and no stage may introduce
information that is not already present in its declared inputs.

## 3. Architectural Components

### 3.1 PDF Upload
Entry point. Accepts a scanned patient PDF and registers it against a
`Patient` record identified by `patient_id`. No interpretation of
content occurs here.

### 3.2 OCR Tool
Performs OCR on each page of the PDF and emits, per page:

- raw recognized text,
- `ocr_confidence`, representing confidence in text recognition,
- `page_image_path`, pointing to the stored image for that page,
- character offsets that anchor each text span back to a page region.

OCR is treated as an idempotent tool that can be re-invoked for
individual pages — never for the full document.

### 3.3 Page Store
The canonical store of OCR output, keyed by `(patient_id, page_number)`.
It is the **only** surface from which evidence may later be extracted
and the only surface the OCR Retry Tool writes back to. Each `Page`
record includes `page_image_path`, which the OCR Retry Tool uses to
retry OCR on the stored page image instead of re-rendering the entire
PDF.

### 3.4 Evidence Extraction Tool
Reads pages from the Page Store and emits structured `Evidence`
records. Every record carries the exact span (`source_start_char`,
`source_end_char`) within `source_text` on a specific
`(document_name, page_number)`. Extraction never produces an evidence
record without a complete provenance triplet.

### 3.5 Evidence Validation Tool (first-class component)

Evidence Validation is a first-class architectural component, not a
processing afterthought. It is the gate that protects the Evidence
Store from polluted data and is responsible for enforcing the
no-hallucination invariant.

Responsibilities:

- Reject records with missing required fields.
- Reject records with invalid dates.
- Detect and de-duplicate equivalent evidence.
- Reject records with invalid `ocr_confidence` or
  `extraction_confidence` values.
- Reject records with broken provenance references
  (missing `document_name`, `page_number`, `source_text`,
  `source_start_char`, or `source_end_char`).
- Reject records whose provenance span is invalid:
  `source_start_char < 0`,
  `source_end_char <= source_start_char`, or
  `source_end_char > len(source_text)`.
- Reject records with empty values where values are required.

Outputs:

- **Validated Evidence** persisted to the Evidence Store.
- **Review Flags** emitted for any record that cannot be admitted
  but represents a clinically relevant signal (for example, a partial
  medication record).

### 3.6 Evidence Store
Persists validated `Evidence` records together with their full
provenance. It is the only input surface for the agent loop and the
summary generator.

### 3.7 Agent State

The Agent State is the working memory of the loop. It is an explicit,
inspectable object that the planner and executor read from and write
to. It contains:

- `patient_id` (references the `Patient` record)
- `iteration`
- `current_goal`
- `completed_goals`
- `pending_goals`
- `conflicts`
- `review_flags`
- `low_confidence_pages`
- `evidence_count`
- `completion_score`
- `summary_ready`
- `max_iterations_reached`

`completion_score` is a numeric readiness signal computed from the
state. The planner uses it — rather than a simple boolean — to decide
when the agent has enough validated evidence to proceed to summary
generation.

### 3.8 Agent Loop

The agent loop is a bounded planner–executor cycle that reasons over
Agent State and acts only through declared tools. The loop terminates
when `summary_ready` becomes true (driven by `completion_score`) or
when `max_iterations_reached` is reached.

Tools available to the loop:

- **Missing Data Tool** — identifies required fields with no supporting
  evidence and either requests targeted re-OCR or raises a review flag.
- **Conflict Detection Tool** — finds disagreements between evidence
  items referring to the same field; produces self-contained
  `Conflict` records.
- **Medication Reconciliation Tool** — consolidates medication evidence
  across documents while preserving every source reference.
- **Pending Results Tool** — identifies clinical results marked as
  pending in the source and surfaces them as review flags.
- **OCR Retry Tool** — reads `low_confidence_pages` from Agent State
  and re-invokes the OCR Tool only for those pages, using each page's
  stored `page_image_path`; writes back to the Page Store.
- **Review Flag Tool** — produces `ReviewFlag` records that reference
  the underlying `Evidence` they were derived from.

Every planner decision, every tool invocation, every state transition,
and every produced artifact is recorded as a `TraceStep`.

### 3.9 Summary Generator
Composes a `DischargeSummary` strictly from validated evidence in the
Evidence Store. It does not call OCR, does not re-read the PDF, and
does not synthesize facts that are absent from the Evidence Store.

### 3.10 Structured Draft (DischargeSummary)
The output of summary generation is a structured `DischargeSummary`
object, not free-form text. It carries the patient identifier, the
clinical content, and the active review flags.

### 3.11 Trace Output
A sequence of `TraceStep` records sufficient to reconstruct every
decision the agent took and every fact in the final summary. The trace
is a first-class output of the system.

## 4. Schemas

The architecture is anchored by a small set of explicit schemas. All
inter-component communication conforms to these contracts.

| Schema            | Role                                                       |
|-------------------|------------------------------------------------------------|
| `Patient`         | The patient-level record that anchors all other artifacts. |
| `Page`            | OCR output for a single PDF page with image path, OCR confidence, and offsets. |
| `Evidence`        | A single extracted, provenance-bearing fact.               |
| `Conflict`        | A detected disagreement between two or more evidence items. |
| `ReviewFlag`      | A condition requiring human attention, linked to evidence. |
| `AgentState`      | Working memory of the agent loop.                          |
| `TraceStep`       | One recorded step in the agent's reasoning, including execution status. |
| `DischargeSummary`| The final structured output.                               |

### 4.1 `Patient` (fields)

Every `Patient` record must support:

- `patient_id`
- `patient_name`
- `age`
- `gender`
- `documents`
- `created_at`

`Patient` is the first-class anchor for the entire system. All other
artifacts — `Page`, `Evidence`, `Conflict`, `ReviewFlag`,
`AgentState`, `TraceStep`, `DischargeSummary` — reference a patient
via `patient_id` and are grouped by it. `documents` is the list of
document names ingested for that patient. `patient_name`, `age`, and
`gender` are optional and may be unknown when extraction is
incomplete; they are never fabricated.

### 4.2 `Page` (fields)

Every `Page` record must support:

- `patient_id` (references the `Patient` record)
- `document_name`
- `page_number`
- `page_image_path`
- `raw_text`
- `ocr_status`
- `ocr_confidence`

`patient_id` ties the page to its owning `Patient`. `document_name`
and `page_number` together address the page within a document and are
the provenance keys that `Evidence` records carry forward.
`page_image_path` points to the stored image for a single page; the
OCR Retry Tool uses this path when retrying pages with low
`ocr_confidence` and does not re-render the full PDF. `raw_text` is
the OCR-recognized text from which `Evidence` is extracted, and the
provenance pair `(source_start_char, source_end_char)` on each
`Evidence` indexes into `raw_text`. `ocr_status` tracks the OCR
lifecycle for the page. `ocr_confidence` represents confidence in
text recognition and is the signal used to populate
`AgentState.low_confidence_pages`.

### 4.3 `Evidence` (fields)

Every `Evidence` record must support:

- `evidence_id`
- `evidence_type`
- `field_name`
- `field_value`
- `document_name`
- `page_number`
- `source_text`
- `source_start_char`
- `source_end_char`
- `section`
- `ocr_confidence`
- `extraction_confidence`
- `extraction_method`
- `status`

The four provenance fields — `document_name`, `page_number`,
`source_text`, and the `(source_start_char, source_end_char)` pair —
together guarantee that every fact can be traced back to the exact
originating text span on a specific page of a specific document.

`evidence_type` identifies the clinical or administrative class of
the fact, such as `diagnosis`, `medication`, `allergy`, `lab_result`,
`demographic`, `follow_up`, or `pending_result`. `field_name`
identifies the specific field being extracted. `field_value` contains
the extracted value. For example:
`evidence_type = medication`, `field_name = medication_name`,
`field_value = metformin`. This separation prevents ambiguity during
medication reconciliation and conflict detection.

`ocr_confidence` represents confidence in text recognition. It is
inherited from OCR output. `extraction_confidence` represents
confidence that the structured value was correctly extracted from the
recognized text. They are distinct signals and must not be collapsed
into a single confidence field.

### 4.4 `Conflict` (fields)

Every `Conflict` record must support:

- `field_name`
- `conflicting_values`
- `evidence_ids`

`conflicting_values` is a list of the values in disagreement.
`evidence_ids` is a list of the evidence records supporting those
values. Conflict objects must be self-contained and auditable without
requiring a re-query of the Evidence Store to understand the disputed
field, disputed values, or supporting evidence.

### 4.5 `ReviewFlag` (fields)

Every `ReviewFlag` must support:

- `flag_id`
- `category`
- `severity`
- `message`
- `evidence_ids`
- `related_page`
- `created_at`
- `status`

`evidence_ids` makes review flags structurally grounded in the
Evidence Store: a flag never floats free of the evidence it concerns.

### 4.6 `AgentState` (fields)

Every `AgentState` record must support:

- `patient_id` (references the `Patient` record)
- `iteration`
- `current_goal`
- `completed_goals`
- `pending_goals`
- `conflicts`
- `review_flags`
- `low_confidence_pages`
- `evidence_count`
- `completion_score`
- `summary_ready`
- `max_iterations_reached`

See §3.7. The presence of `completion_score`, `summary_ready`, and
`max_iterations_reached` allows the planner to reason about readiness
as a graded signal rather than a single boolean. The OCR Retry Tool
uses `low_confidence_pages` directly instead of rescanning all stored
pages.

### 4.7 `TraceStep` (fields)

Every `TraceStep` must include:

- `trace_id`
- `patient_id` (references the `Patient` record)
- `iteration`
- `goal`
- `selected_tool`
- `tool_input`
- `tool_output`
- `decision`
- `status`
- `timestamp`

Allowed `status` values are:

- `SUCCESS`
- `FAILED`
- `RETRY`
- `SKIPPED`

`trace_id` uniquely identifies the step. `patient_id` ties the step
to its owning `Patient`. `iteration` allows the trace to be replayed
grouped by agent-loop iteration. `goal` records the active goal at
the time of the step. `selected_tool` names the tool the planner
chose. `tool_input` and `tool_output` capture the exact data passed
into and produced by that tool. `decision` records the planner or
executor decision that led to or resulted from the step. `status`
records the outcome of the planner decision, tool invocation,
executor action, or state transition. `timestamp` records when the
step occurred. Together these fields make the trace sufficient to
fully reconstruct and audit the agent's behavior.

### 4.8 `DischargeSummary` (fields)

The `DischargeSummary` is a first-class schema, not a string. It must
support:

- `patient_id` (references the `Patient` record)
- `diagnoses`
- `medications`
- `allergies`
- `procedures`
- `pending_results`
- `follow_up_instructions`
- `review_flags`
- `supporting_evidence_ids`
- `generated_at`

`diagnoses`, `medications`, `allergies`, `procedures`,
`pending_results`, and `follow_up_instructions` are lists of
structured entries. `review_flags` is a list of review flag
identifiers. Every entry in any of these clinical lists must be
traceable to one or more entries in `supporting_evidence_ids`, each
of which resolves to an `Evidence` record carrying exact-span
provenance.

## 5. Cross-Cutting Principles

### 5.1 Evidence-Based Extraction
Every fact in the system is an `Evidence` record with a complete
provenance triplet (`document_name`, `page_number`,
`source_text` + char span).

### 5.2 No Hallucination
Missing information is represented as missing. No component may
fabricate, default, or infer a value that is not present in the
source.

### 5.3 Exact-Span Provenance
Provenance is not just "this page" — it is the exact character range
(`source_start_char`, `source_end_char`) within a quoted `source_text`
on a specific `(document_name, page_number)`. This is enforced at the
schema level for `Evidence` and inherited by every downstream output.
Validation rejects spans where `source_start_char` is negative,
`source_end_char` is not greater than `source_start_char`, or
`source_end_char` exceeds the length of `source_text`.

### 5.4 Conflict Detection
Disagreements between evidence items are surfaced as `Conflict`
records and as `ReviewFlag`s. They are never silently resolved by the
agent.

### 5.5 Review Flags
Review flags are first-class outputs. They always reference the
`Evidence` they concern via `evidence_ids` and are propagated into the
`DischargeSummary`.

### 5.6 Traceability
Every planner decision, executor action, tool invocation, and state
transition is recorded as a `TraceStep`. The trace is sufficient to
reconstruct why each line of the discharge summary exists.

### 5.7 Targeted OCR Retry
OCR retries are scoped to specific pages with low `ocr_confidence`
via the OCR Retry Tool. Retries use the stored `page_image_path` on
the `Page` record and do not re-render the entire PDF.

### 5.8 Bounded Agent Loop
The agent loop is bounded by a configurable maximum iteration count,
`MAX_AGENT_ITERATIONS`. The loop terminates when, and only when, one
of the following holds:

- `summary_ready == True`, **or**
- `max_iterations_reached == True`.

`max_iterations_reached` is derived from `AgentState.iteration`
against `MAX_AGENT_ITERATIONS`. The planner must never produce a plan
that can sustain an infinite loop. Every iteration of the loop
increments `AgentState.iteration` by exactly one, and incrementing
that counter is the responsibility of the executor — no other
component is permitted to mutate `AgentState.iteration`.

### 5.9 Summary Generation Only From Validated Evidence
The Summary Generator reads only from the Evidence Store. It cannot
call OCR, cannot read pages, and cannot introduce content beyond what
the Evidence Store and review flags provide.

## 6. Module Layout

The source tree mirrors the architectural boundaries:

- `src/schemas/` — `Patient`, `Page`, `Evidence`, `Conflict`,
  `ReviewFlag`, `AgentState`, `TraceStep`, `DischargeSummary`.
- `src/storage/` — Page Store, Evidence Store, trace persistence,
  review flag persistence, conflict persistence, patient loaders.
- `src/tools/` — OCR Tool, Evidence Extraction Tool, Evidence
  Validation Tool, plus the agent-loop tools (Missing Data, Conflict
  Detection, Medication Reconciliation, Pending Results, OCR Retry,
  Review Flag).
- `src/services/` — higher-level orchestrations that compose tools
  (extraction pipeline, validation pipeline, reconciliation,
  conflict detection, summary generation).
- `src/agent/` — Agent State, Planner, Executor, Trace System,
  Agent Loop.
- `src/prompts/` — prompt assets used by AI-driven components.

## 7. Design Principles

- **Schemas first.** No inter-component data exists outside a declared
  schema.
- **Validation as a gate, not a step.** Evidence Validation is a
  first-class component whose job is to keep the Evidence Store
  trustworthy.
- **Exact-span provenance everywhere.** Provenance is enforced at the
  smallest meaningful unit: a character range inside a quoted text on
  a specific page.
- **Bounded, observable agency.** The agent's autonomy is constrained
  by its tools, its state, and its trace.
- **Deterministic auditability.** Any output fact can be reconstructed
  from `DischargeSummary.supporting_evidence_ids` to `Evidence`, then
  from `source_text` and its character span to the originating page.
