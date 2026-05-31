# Agent Memory Research Alignment Plan

**Date:** 2026-05-31
**Status:** Proposed
**Source research:** `../DEEP-RESEARCH-REQUEST-RESPONSE.md`
**Baseline design:** `agent-memory-design.md`
**Implemented baseline:** PLAN-1 through PLAN-4 complete

---

## Purpose

This document compares the deep research recommendations against the current
`agent_memory` design and implementation, then defines an overarching plan for
bringing the module into closer alignment with the research.

The goal is not to replace the current architecture. The research largely
validates the local-first Markdown plus SQLite approach. The goal is to harden
the system into a layered, schema-aware memory service with better retrieval,
classification, compaction, and handoff semantics.

---

## Current Alignment

### Markdown plus YAML remains the source of truth

The research strongly supports keeping Markdown plus YAML frontmatter for
human-editable, git-friendly memory. This aligns with the current design and
implementation:

- one Markdown file per note
- YAML frontmatter for metadata
- Markdown body for human-readable content
- SQLite index as a rebuildable cache, not the canonical store

No format migration away from Markdown is recommended.

### SQLite FTS5 remains the right local search default

The research supports SQLite FTS5 for the expected 1K to 50K note range. This
aligns with the current `NoteIndex` design:

- local SQLite index
- FTS5 when available
- LIKE fallback when FTS5 is unavailable
- WAL mode enabled

The recommendation is to improve tokenizer/ranking behavior before considering
another search engine.

### Local LLM routing is appropriate when tightly scoped

The current PLAN-4 implementation uses deterministic placement rules first and
then uses the local LLM only for ambiguous note placement. This aligns with the
research recommendation to keep local LLM use narrow and low-risk.

The current implementation also degrades gracefully when `llm_local` is missing
or unavailable, which matches the research preference for always-working local
behavior.

### Handoff notes are a valid first-class kind

The research validates `handoff` as an important memory kind for heterogeneous
agent workflows. This aligns with the current taxonomy and the intended
`agent_sync` integration.

---

## Current Misalignments

### The taxonomy is too flat for long-term operation

Current kinds:

- `constraint`
- `preference`
- `decision`
- `code_note`
- `handoff`
- `task`
- `bug`
- `session`

Research recommendations:

- keep `constraint`, `preference`, `decision`, `handoff`, `bug`, and `code_note`
- convert `session` from a primary kind into metadata/provenance where possible
- split `task` into short-lived `task_state` and durable `task_lesson`
- add `environment`, `procedure`, and `evidence`
- add layered memory semantics: core, archival, reflective

Current implementation has no layer/scope distinction beyond `global` versus
project. It also lacks note lifecycle fields needed for compaction and
injection decisions.

### Frontmatter schema is too small for lifecycle management

Current V1 frontmatter fields:

- `id`
- `schema_version`
- `kind`
- `project`
- `created_at`
- `created_by`
- `tags`

Research recommends adding stable metadata for:

- `title`
- `scope` or layer
- `updated_at`
- `status`
- `supersedes`
- `superseded_by`
- `related`
- `source_agent`
- `session_id`
- `confidence`

The current implementation stores title only in the body and does not support
note lifecycle, provenance, or relationship metadata.

### YAML parsing and validation are not hardened enough

Current frontmatter validation checks only missing required fields. It does not
yet validate:

- field types
- scalar ambiguity from YAML auto-typing
- known kind values
- known status values
- expected project/path consistency in all cases
- invalid or duplicate IDs across files
- recoverable parse failures
- UTF-8 BOM handling

The research specifically calls out YAML ambiguity and recovery behavior as
important failure modes.

### LLM classification returns plain text instead of a structured decision

Current classifier output:

- accepts raw `"global"` or `"<project-slug>"`
- strips quotes and validates the slug
- returns only a string

Research recommends a strict schema:

```json
{
  "scope": "global | project",
  "project_slug": "string | null",
  "confidence": 0.0,
  "reason_code": "cross_project_preference | repo_specific_fact | environment_fact | workflow_rule | unclear",
  "needs_user_confirmation": false
}
```

The current classifier has no confidence threshold, reason code, known-project
matching, few-shot prompt examples, or structured-output path.

### Search is functional but not code-aware

Current FTS schema:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
    USING fts5(title, body_excerpt, content=notes, content_rowid=rowid);
```

Research recommends:

- code-aware `unicode61` tokenizer configuration
- preserving identifiers such as snake_case names, flags, and paths
- keeping token search as the default
- adding partial identifier search only as a targeted secondary capability
- adding ranking/reranking rather than another lexical index

Current search returns unordered FTS results and has no snippet/rank metadata.

### There is no retrieval or context injection API

The current API has `list_notes()` and `search()`, but no explicit method for
building agent context. The research recommends ordering injected context by:

1. stable core constraints
2. current project profile
3. retrieved evidence near the active request
4. current handoff or goal summary near the end

Current implementation leaves this ordering to callers.

### There is no compaction, supersession, or reflective memory layer

The current system can create, list, search, show, edit, rebuild, and verify
notes. It cannot:

- detect duplicate or near-duplicate notes
- mark notes superseded
- merge note families
- expire short-lived task state
- synthesize reflective notes
- ask for human review before lossy consolidation

Research recommends deterministic candidate selection first, then structured
LLM-assisted merge decisions.

### Handoff semantics are not yet standardized

The current design has `handoff` as a kind, but does not define a strict handoff
schema. The research recommends a two-part handoff artifact:

- machine-readable JSON header
- short human-readable Markdown narrative

It also recommends a receiving-agent acknowledgment step before edits begin.
This belongs mostly in `agent_sync`, but `agent_memory` should define and
validate the note shape.

---

## Overarching Implementation Plan

This work should be split into sub-plans. Each sub-plan should be small enough
to implement, test, and commit independently, following the existing
`PLAN-1` through `PLAN-4` pattern.

### Phase 5: Schema V2 and taxonomy alignment

**Goal:** Extend the note model so future retrieval, compaction, and handoff
features have stable metadata to work with.

**In scope:**

- introduce frontmatter schema version 2
- add lifecycle/provenance fields
- add new note kinds
- keep V1 notes readable
- add migration helpers but avoid destructive rewrites by default

**Proposed fields:**

Required for V2 agent-created notes:

- `id`
- `schema_version`
- `kind`
- `project`
- `title`
- `created_at`
- `created_by`
- `updated_at`
- `updated_by`
- `status`
- `tags`

Optional V2 fields:

- `layer`: `core`, `archival`, or `reflective`
- `source_agent`
- `session_id`
- `confidence`
- `related`
- `supersedes`
- `superseded_by`
- `evidence_for`
- `review_required`

Taxonomy changes:

- keep `constraint`, `preference`, `decision`, `code_note`, `handoff`, `bug`
- add `environment`, `procedure`, `evidence`, `task_state`, `task_lesson`,
  `reflection`
- deprecate `task` in favor of `task_state` and `task_lesson`
- deprecate `session` as a primary kind, but continue reading old `session`
  notes for compatibility

**Sub-plan deliverables:**

- update `note.py` constants and dataclass
- update `frontmatter.py` parse/write/validate behavior
- update `store.py` note creation and readback
- add `agent-memory migrate` or `agent-memory index verify --schema` only if
  the CLI scope remains small enough
- update tests for V1 compatibility and V2 writes

### Phase 6: Harden frontmatter validation and recovery

**Goal:** Make human-edited notes safe to index and recoverable when metadata is
invalid.

**In scope:**

- validate field types and enum values
- validate path/project/kind consistency
- detect duplicate note IDs during verify/rebuild
- handle UTF-8 BOM at file start
- preserve body text when frontmatter is invalid
- report actionable recovery suggestions

**Out of scope:**

- automatic destructive repair
- mass rewriting all notes without an explicit command

**Sub-plan deliverables:**

- introduce structured validation errors
- add `NoteValidationError` or equivalent typed error model
- make `verify()` return richer diagnostics while preserving simple CLI output
- add tests for malformed YAML, scalar auto-typing, missing fields, duplicate
  IDs, kind/path mismatch, and BOM handling

### Phase 7: Structured placement classification

**Goal:** Replace plain text placement classification with a structured decision
object that includes confidence, reason code, and user-confirmation policy.

**In scope:**

- add `PlacementDecision` dataclass
- add deterministic pre-rules before LLM calls
- include known projects in the prompt
- use a few-shot prompt with explicit examples
- parse JSON/structured output when possible
- retain plain-text fallback for older `llm_local` behavior
- apply confidence thresholds

**Proposed policy:**

- `confidence >= 0.85`: auto-apply
- `0.60 <= confidence < 0.85`: auto-apply only if deterministic heuristic agrees
- `confidence < 0.60`: require interactive confirmation when possible
- non-interactive uncertain cases default to `global` unless the caller passes
  an explicit project

**Sub-plan deliverables:**

- update `llm_local.complete()` only if structured-output support needs a new
  optional parameter
- update `classify.py` to return and consume `PlacementDecision`
- update `NoteStore.create_note()` to store placement confidence/reason in V2
  frontmatter when available
- add tests for JSON output, malformed JSON, confidence thresholds, known
  project matching, and non-interactive fallback

### Phase 8: Code-aware FTS5 search and ranking

**Goal:** Improve local search quality for code-heavy memory without replacing
SQLite FTS5.

**In scope:**

- configure FTS5 with code-aware `unicode61` tokenization
- preserve underscores and selected identifier/path punctuation
- add BM25 rank ordering from FTS5
- optionally return snippets or match metadata
- add targeted partial identifier search only if needed

**Out of scope:**

- replacing SQLite with Tantivy, DuckDB, Whoosh, or MiniSearch
- adding dense embeddings in `agent_memory` V1

**Sub-plan deliverables:**

- revise `_FTS_DDL`
- add index versioning/rebuild behavior for tokenizer changes
- update `search()` ordering to use rank
- add tests for snake_case, kebab-case flags, paths, exact error strings, and
  ordinary prose

### Phase 9: Retrieval and context injection API

**Goal:** Add an explicit API for selecting and ordering memories for a new
agent session.

**In scope:**

- add `retrieve_context()` or equivalent API
- support project, active query, changed files, note kinds, and token/character
  budget
- prioritize core constraints and preferences
- include current project profile and current handoff
- place retrieved evidence near the active request
- produce deterministic, inspectable ordering

**Out of scope:**

- provider-specific prompt caching integrations
- dense vector retrieval

**Sub-plan deliverables:**

- define a `ContextBundle` dataclass
- implement deterministic context selection from SQLite results
- add CLI command such as `agent-memory context build`
- add tests for ordering, limits, kind priority, recency, and relevance

### Phase 10: Compaction, supersession, and reflective notes

**Goal:** Add controlled memory consolidation without losing evidence or human
trust.

**In scope:**

- deterministic candidate discovery
- supersession metadata
- duplicate detection by exact content hash and shared title/kind/project
- stale `task_state` detection
- structured LLM merge recommendations
- dry-run first CLI workflow
- human review flag for uncertain merges

**Out of scope:**

- automatic deletion of notes
- background daemon behavior

**Sub-plan deliverables:**

- add `agent-memory compact plan`
- add `agent-memory compact apply`
- add `reflection` notes as synthesized summaries
- preserve original notes and mark them superseded instead of deleting
- add tests for merge candidates, dry-run output, status changes, and index
  rebuild after compaction

### Phase 11: Handoff schema and acknowledgment support

**Goal:** Standardize handoff notes for heterogeneous agents and prepare
`agent_sync` integration.

**In scope for `agent_memory`:**

- define handoff note body/header schema
- validate handoff notes
- provide helper to create handoff notes
- support machine-readable JSON block plus Markdown narrative

**In scope for later `agent_sync`:**

- write handoff notes using the schema
- require receiving-agent acknowledgment before edits
- store ACK as a memory note or coordination event

**Sub-plan deliverables:**

- add `handoff.py` or equivalent helper module
- add tests for required handoff fields:
  - `goal`
  - `current_status`
  - `completed_steps`
  - `pending_steps`
  - `changed_files`
  - `test_results`
  - `known_blockers`
  - `decisions`
  - `assumptions`
  - `requested_next_action`
  - `confidence`
- add CLI helper such as `agent-memory handoff create` only if it does not
  duplicate `agent_sync`

### Phase 12: Repository and performance ergonomics

**Goal:** Keep the note store usable as it grows.

**In scope:**

- document recommended Git settings such as untracked cache and fsmonitor
- evaluate project-first plus optional date/prefix sharding
- add benchmark script for index rebuild/search at synthetic note counts
- keep sharding backward-compatible

**Out of scope:**

- mandatory repository-wide Git configuration changes
- migration to a non-Markdown format

**Sub-plan deliverables:**

- add docs for Git and filesystem performance
- add benchmark fixture/script under module-local tests or tooling
- define when sharding should be introduced
- add tests for old and new path layouts if sharding is implemented

---

## Recommended Sub-Plan Order

1. **PLAN-5-SCHEMA-V2.md**
   Add taxonomy, lifecycle metadata, V1 compatibility, and validation shape.

2. **PLAN-6-FRONTMATTER-HARDENING.md**
   Tighten validation, duplicate detection, recovery behavior, and verify
   diagnostics.

3. **PLAN-7-STRUCTURED-CLASSIFY.md**
   Replace plain-text classifier decisions with structured output, confidence,
   and deterministic pre-rules.

4. **PLAN-8-SEARCH-RANKING.md**
   Improve FTS5 tokenizer, ranking, and code identifier search behavior.

5. **PLAN-9-CONTEXT-RETRIEVAL.md**
   Add a memory selection and context ordering API for agent startup.

6. **PLAN-10-COMPACTION.md**
   Add supersession, duplicate/stale detection, reflective notes, and dry-run
   compaction.

7. **PLAN-11-HANDOFF-SCHEMA.md**
   Define structured handoff artifacts and ACK expectations for later
   `agent_sync` work.

8. **PLAN-12-PERFORMANCE-ERGONOMICS.md**
   Add Git/search/index benchmarks and documented scaling guidance.

---

## Implementation Principles

- Preserve Markdown files as the canonical source of truth.
- Preserve V1 note readability while introducing V2 writes.
- Prefer additive schema changes before strict migrations.
- Keep SQLite FTS5 as the default index.
- Use deterministic rules before LLM calls.
- Require dry-run behavior for compaction and migration commands.
- Preserve old notes by marking them superseded rather than deleting them.
- Keep CLI flags compliant with repository standards: every user-facing option
  must have both a short and long form.
- Run the full module test suite before completing each sub-plan.

---

## Open Questions

1. Should `session` remain as a deprecated readable kind forever, or should a
   migration eventually convert it into `handoff`, `task_state`, or metadata?
2. Should V2 use `project` only, or add an explicit `scope` field in addition to
   `project="global"`?
3. Should structured LLM output require an enhancement to `llm_local`, or should
   `agent_memory` initially request JSON in the prompt and parse it locally?
4. Should context retrieval live only in `agent_memory`, or should `agent_sync`
   own agent-specific prompt assembly?
