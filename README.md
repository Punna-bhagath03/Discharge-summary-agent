# Discharge Summary Agent

A Python system for turning clinical source material into a structured, auditable discharge summary. The design assumes scanned or OCR'd notes where text is noisy, fields are incomplete, and the cost of inventing a fact is much higher than the cost of leaving a gap.

This repository is a take-home implementation shaped by `docs/architecture.md`, `docs/requirements.md`, and `docs/implementation_plan.md`. The code in `src/` is the source of truth for what actually runs today.

## 1. Project Overview

Hospital discharge summaries are usually written under time pressure from charts, nursing notes, medication lists, and assorted PDFs. In practice those sources are inconsistent: OCR drops characters, sections are duplicated across documents, and the same field can disagree between pages.

The goal here is not to produce fluent prose for its own sake. The goal is to build a pipeline where every clinical statement in the output can be traced back to a specific span of source text, and where unknown or disputed information is surfaced for review instead of guessed.

Clinical safety and non-fabrication are treated as primary constraints. The architecture rejects the pattern of asking a model to "fill in" a summary from raw notes. Facts live in an Evidence Store first; a summary is assembled only from validated evidence. If something cannot be supported, it should be absent or flagged—not invented.

The intended shape is a bounded agent loop over stored evidence: read state, choose a tool, persist results, record trace steps, and eventually emit a structured `DischargeSummary` plus review workload. Extraction and validation happen before planning and synthesis so downstream stages never have to repair polluted inputs.

## 2. Design Decisions

### Structured schemas instead of loose dictionaries

Inter-component data is defined as Pydantic models under `src/schemas/` (`Patient`, `Page`, `Evidence`, `Conflict`, `ReviewFlag`, `AgentState`, `TraceStep`, `DischargeSummary`). That choice is slower upfront than passing dicts around, but it makes contracts explicit and gives a stable surface for storage, tools, and tests.

A simpler alternative would be JSON blobs end-to-end. That works for a demo but breaks down once you need to enforce provenance fields, prove what a tool is allowed to emit, and audit outputs in a regulated setting.

### Evidence separate from the summary

`Evidence` records are the canonical facts. `DischargeSummary` entries reference `supporting_evidence_ids` rather than embedding free text copied from charts.

That separation means the summary generator cannot silently add clinical content without going through the Evidence Store. It also lets conflict detection and review flags operate on facts before anyone sees a draft summary.

### Provenance on every fact

Each `Evidence` record carries `document_name`, `page_number`, `source_text`, and a character span (`source_start_char`, `source_end_char`). Validation rejects broken spans. Extraction is rule-based and copies section labels from matched text rather than normalizing them to a friendly display name.

Exact-span provenance is more work than storing "page 3" alone, but it is the only workable audit path: reviewer → summary entry → evidence id → quoted source text → character range.

### Validation as a gate, not an afterthought

Phase 5 (`EvidenceValidationTool` / `EvidenceValidationService`) sits between extraction and the Evidence Store. Invalid records never reach `save_evidence()`. Duplicates are detected by provenance identity, not by semantic similarity.

The alternative—letting everything into storage and filtering later—would push complexity into the agent loop and make it harder to reason about what the planner actually saw.

### Conflict detection and review flags as separate stages

The architecture treats disagreements (`Conflict`) and human attention items (`ReviewFlag`) as different artifacts. Phase 7 detects field-level value conflicts across validated evidence and persists both a `Conflict` and a paired flag. Phase 8 surfaces pending-result evidence as flags with a different category and severity policy.

Keeping those stages separate avoids overloading a single "warning" type and matches how clinicians think: a data conflict is not the same thing as a pending lab.

Policy details for Phase 7 and 8 live in `docs/adr/` (ADR-007 through ADR-017) because the base documents required fields but not generation rules.

## 3. Agent Loop Design

Intended end-to-end flow from the architecture documents:

```
PDF upload → OCR → Page Store → Evidence extraction → Evidence validation
→ Evidence Store → (reconciliation, conflict detection, pending results)
→ Agent state → Planner → Executor → Trace → DischargeSummary
```

Status by stage (verified against this repository):

| Stage | Planned | Implemented in code |
|-------|---------|---------------------|
| PDF upload / ingestion | Yes | No |
| OCR Tool (Phase 3) | Yes | No — `Page` records must be loaded manually |
| Evidence extraction (Phase 4) | Yes | Yes — rule-based `EvidenceExtractionTool` |
| Evidence validation (Phase 5) | Yes | Yes — gate to Evidence Store |
| Medication reconciliation (Phase 6) | Yes | Yes — in-memory view, no writes |
| Conflict detection (Phase 7) | Yes | Yes |
| Pending results (Phase 8) | Yes | Yes |
| Agent state (Phase 9) | Yes | Yes — `AgentStateManager` |
| Planner (Phase 10) | Yes | Yes — deterministic `Planner` |
| Executor (Phase 11) | Yes | Yes — `Executor` |
| Trace system (Phase 12) | Yes | Yes — `TraceSystem` → `save_trace()` |
| Summary generation (Phase 13) | Yes | Yes — deterministic mapping from evidence |
| Missing Data Tool | Yes | No |
| OCR Retry Tool | Yes | No |
| Review Flag Tool (generic) | Yes | No |

What exists for orchestration: `build_agent_loop()` in `src/agent/wiring.py` wires storage, planner, executor, trace, and the Phase 7/8/13 services into `AgentLoop.run(patient_id)`. That loop assumes evidence is already in the store. It does not ingest PDFs or run OCR.

## 4. What Was Implemented

### Schemas (Phase 1)

All first-class types under `src/schemas/`: `Patient`, `Page`, `Evidence`, `Conflict`, `ReviewFlag`, `AgentState`, `TraceStep`, `DischargeSummary`, plus enums (`EvidenceType`, `ReviewSeverity`, `TraceStatus`).

### Storage (Phase 2)

`StorageService` in `src/storage/storage_service.py` — in-memory persistence for patients, pages, evidence, conflicts, review flags, and trace steps. This is the only layer that writes those artifacts.

### Evidence pipeline (Phases 4–6)

- `EvidenceExtractionTool` / `EvidenceExtractionService` — reads `Page` records, emits `Evidence` with provenance (not persisted by extraction itself).
- `EvidenceValidationTool` / `EvidenceValidationService` — validates, deduplicates by exact span, persists via `save_evidence()`.
- `MedicationReconciliationTool` / `MedicationReconciliationService` — groups medication evidence by `field_name`, returns existing records in memory.

### Agent-loop tools (Phases 7–8)

- `ConflictDetectionTool` / `ConflictDetectionService` — detects same-field value disagreements, persists `Conflict` and `ReviewFlag` records.
- `PendingResultsTool` / `PendingResultsService` — one review flag per `PENDING_RESULT` evidence record.

### Agent core (Phases 9–12)

- `AgentStateManager` — immutable state transitions, storage refresh helpers, `set_completion_score()`, `set_summary_ready()`, `increment_iteration()` (executor-only iteration changes).
- `Planner` — fixed goal sequence: conflicts → medication reconciliation → pending results → summary; computes a bounded `completion_score`.
- `Executor` — runs the wired tools, refreshes state, records trace steps.
- `TraceSystem` — append-only `TraceStep` persistence via `save_trace()` (tool I/O logged as aggregate JSON without clinical field values).

### Summary (Phase 13)

- `SummaryGenerationService` — builds `DischargeSummary` from stored evidence and review flag ids. Mapping is deterministic (one `SummaryEntry` per evidence record for supported types). `src/prompts/` is a placeholder for future prompt assets; the current generator does not call an LLM.

### Documentation and policy

- `docs/architecture.md`, `docs/requirements.md`, `docs/implementation_plan.md`
- `docs/adr/` — ADR-007 through ADR-017 for Phase 7/8 field-population rules

### Tests

`tests/test_phases_7_13.py` — six integration tests covering conflict detection, pending results, summary generation, planner scoring bounds, and a minimal agent-loop run. This is a thin slice, not full phase coverage.

## 5. Current Status

What works today if you seed data yourself:

1. Create a `Patient` and `Page` records in `StorageService`.
2. Run extraction → validation to populate the Evidence Store.
3. Call individual services (conflict, pending results, summary) or `build_agent_loop().run(patient_id)` with validated evidence present.

The agent loop can terminate with a `DischargeSummary`, stored conflicts/flags, and trace steps for that patient id.

Partial:

- Phase 5 validation drops rejected records instead of emitting ReviewFlags (documented gap in `evidence_validation_service.py`; FR-22 allows flags but taxonomy for rejected clinical relevance was not defined).
- End-to-end flow from a real PDF is not wired: no OCR, no upload handler, no CLI.
- Summary and extraction are rule-based/heuristic, not model-driven.
- Storage is in-process only; restart clears state.

Not implemented:

- Phase 3 OCR Tool and OCR Retry Tool
- Missing Data Tool and generic Review Flag Tool
- Hospital system integration, authentication, deployment
- Broad automated test suite per `implementation_plan.md` §6 Definition of Done

The project is functional in its implemented slices but is not a complete production discharge-summary product.

## 6. Handling Safety and Non-Fabrication

Implemented mechanisms:

- Evidence-first workflow: summary content is built only from `get_evidence_for_patient()` results.
- Validation gate: malformed, duplicate, or provenance-broken candidates do not enter the store.
- Provenance fields enforced on `Evidence` at the schema level.
- Conflict detection: disagreeing values for the same `field_name` produce `Conflict` records and `category=conflict` review flags; values are not merged away in Phase 7.
- Pending results: explicit `PENDING_RESULT` evidence becomes review flags rather than being folded into diagnoses or medications.

The architecture's intent is that missing information stays missing. The extraction rules simply do not emit a field if the pattern does not match. Validation rejects empty required strings. The summary generator does not interpolate defaults.

What is not fully realized: Phase 5 does not yet flag rejected-but-relevant validation failures, so some clinically interesting rejects are dropped silently (with only aggregate rejection counts in debug logs).

## 7. Failure Handling

### Validation failures (implemented)

`EvidenceValidationTool` returns rejection reasons; `EvidenceValidationService` skips persist for failed candidates. Batch processing continues after a single failure.

### Missing evidence (partial)

There is no Missing Data Tool. The planner does not invent facts; an empty Evidence Store yields `completion_score` 0 and blocks `summary_ready` until evidence exists.

### Contradictory evidence (implemented)

`ConflictDetectionService` groups by `field_name`, compares `field_value` with exact string equality, and persists conflicts and flags. Conflicts are not auto-resolved (architecture §5.4). Re-running detection can append additional records; there is no deduplication pass.

### Trace and executor errors (implemented)

Executor tool failures record a `FAILED` trace step and re-raise. Iteration increment is recorded separately.

Not implemented: automated conflict resolution, human workflow for closing flags beyond storing `status="open"` at creation.

## 8. Limitations

- No OCR implementation. Pages must be inserted into storage by test code or ad hoc scripts.
- No PDF ingestion or multi-document upload flow in code.
- Extraction coverage is limited to regular expressions in `evidence_extraction_tool.py`; many chart layouts will not match.
- No LLM-based extraction or summarization in the current paths.
- Several agent-loop tools from the architecture diagram are absent (Missing Data, OCR Retry, generic Review Flag).
- In-memory storage only; no durability, concurrency, or backup.
- Privacy: NFR-9 is respected in service debug logs and trace payloads use summaries, but there is no full redaction audit across all code paths.
- Tests: six integration tests exist; there is no per-phase unit coverage, no CI config in-repo, and no evaluation harness for summary quality.
- `completion_score` weighting in `Planner` is an implementation policy documented in code, not specified in the architecture documents.
- Python 3.12 is documented as the target; local development may use newer interpreters (e.g. 3.14) without explicit compatibility guarantees.

## 9. What I Would Do Next

If I had more time, I would work in this order:

1. Phase 3 OCR Tool — produce `Page` records from PDFs so the pipeline starts from real inputs instead of hand-seeded pages.
2. PDF ingestion entry point — thin CLI or API that registers a `Patient`, runs OCR, extraction, and validation in sequence.
3. Phase 5 ReviewFlags for rejected-but-relevant evidence — ADR for clinical-relevance rules, then wire `save_review_flag()` in the validation service.
4. Missing Data and OCR Retry tools — so the planner can act on `low_confidence_pages` instead of only refreshing them.
5. Testing — unit tests per tool/service, fixture charts, and regression cases for provenance and conflict detection.
6. Evaluation — small labeled set of synthetic notes to measure extraction recall and conflict detection accuracy.
7. Production hardening — persistent storage backend, configuration via environment variables, structured logging, and deployment docs.

Phases 7–13 from the implementation plan are present in this tree; the remaining gap is mainly upstream ingestion, broader tool coverage, and quality assurance around the pieces that already exist.

## 10. Assignment Context

I received the assignment later than intended and worked within a limited remaining time window. I prioritized the parts that constrain everything else: schemas, storage contracts, the evidence extraction and validation path, and then the agent-loop stages that depend on a populated Evidence Store.

That ordering was deliberate. A summary generator or planner is not trustworthy if the evidence layer is vague. ADRs were added where the written architecture required fields but not behavior (conflict and review-flag emission). With more calendar time I would close the OCR and ingestion gap, finish validation-side review flags, expand tests, and run a proper evaluation pass—not because the later phases are unimportant, but because they only matter once facts in the store are reliable.

## Repository Layout

```
docs/                 Architecture, requirements, implementation plan, ADRs
src/schemas/          Pydantic contracts
src/storage/          StorageService (in-memory)
src/tools/            Pure tool logic
src/services/         Orchestration over tools + storage
src/agent/            State manager, planner, executor, trace, agent loop
src/prompts/          Placeholder for future prompt assets
tests/                Integration tests (Phases 7–13 focus)
```

## Documentation

- `docs/architecture.md` — system structure and principles
- `docs/requirements.md` — functional and schema requirements
- `docs/implementation_plan.md` — phased delivery plan
- `docs/adr/` — normative policies for Phase 7 and 8 behavior

## Setup and Tests

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install pydantic pytest
pytest tests/ -q
```

There is no packaged application entry point yet. Use the services and `build_agent_loop()` from `src/agent/wiring.py` in scripts or tests, with data seeded into `StorageService` first.

## License

Not specified in this repository.
