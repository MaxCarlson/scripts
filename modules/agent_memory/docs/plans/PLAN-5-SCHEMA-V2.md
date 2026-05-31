# agent_memory Schema V2 and Taxonomy Alignment — Revised Implementation Plan

> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce frontmatter schema version 2, lifecycle/provenance fields, relationship metadata, indexed metadata required by later phases, and an expanded note taxonomy while preserving V1 read/index compatibility.

**Architecture:** Markdown files remain the canonical source of truth. SQLite remains a rebuildable derived cache, but V2 metadata that later features must filter on is represented in the index from this plan onward. V1 notes remain readable without destructive migration. New agent-created notes write V2 by default.

**Authoritative context:** Use `BROWSER-LLM-SUBPLAN-HANDOFF.md` as the handoff/source prompt for these plans. Do not rely on any stale root `HANDOFF.md` found in bundled repository context.

**Prerequisites:** PLAN-1 through PLAN-4 complete. Read `docs/design/agent-memory-design.md`, `docs/design/agent-memory-research-alignment-plan.md`, and `docs/PROJECT_STATUS.md` before implementing.

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## Dependency Notes

This plan must be completed before PLAN-6 through PLAN-12. Later phases depend on the following decisions from this plan:

- lifecycle status values,
- `review_required` semantics,
- note kind taxonomy,
- layer taxonomy,
- relationship field shape,
- placement policy per kind,
- indexed SQLite columns for V2 metadata,
- deprecated-kind read/create behavior.

---

## File Map

| File | Responsibility |
|---|---|
| `agent_memory/note.py` | Note dataclass, kind/status/layer constants, defaults, relationship fields |
| `agent_memory/frontmatter.py` | V1/V2 schema constants, serialization defaults, compatibility helpers |
| `agent_memory/store.py` | V2 note writes, V1/V2 readback, placement policy integration |
| `agent_memory/index.py` | SQLite schema/index migration for V2 metadata |
| `agent_memory/cli.py` | Minimal optional metadata flags for note creation/listing |
| `tests/note_test.py` | Taxonomy/default metadata coverage |
| `tests/frontmatter_test.py` | V1/V2 schema serialization coverage |
| `tests/store_test.py` | V2 create/read/list/rebuild coverage |
| `tests/index_test.py` | SQLite schema migration and indexed metadata coverage |
| `tests/cli_test.py` | CLI metadata behavior if exposed |
| `docs/PROJECT_STATUS.md` | Project status update |
| `pyproject.toml` | Version bump |
| `agent_memory/__init__.py` | Version bump |

---

## Target Schema V2

### Required fields for new V2 notes

```yaml
id: string
schema_version: 2
kind: string
project: string
title: string
created_at: string  # UTC timestamp
created_by: string
updated_at: string  # UTC timestamp
updated_by: string
status: string
tags: list[string]
```

### Optional fields for V2 notes

```yaml
layer: string
source_agent: string | null
session_id: string | null
confidence: float | null
review_required: bool
classification_reason: string | null
classification_method: string | null
files: list[string]
related: list[string]
supersedes: list[string]
superseded_by: list[string]
evidence_for: list[string]
```

### Status semantics

Use lifecycle `status` for persistence state only:

```text
active
superseded
archived
draft
```

Do **not** use `review_required` as a status. `review_required` is an orthogonal boolean.

Examples:

```yaml
status: active
review_required: true
```

```yaml
status: superseded
review_required: false
```

### Layer semantics

Valid layers:

```text
core
working
archival
reflective
```

Default mapping:

| Kind | Default layer |
|---|---|
| `constraint` | `core` |
| `preference` | `core` |
| `procedure` | `core` |
| `environment` | `core` |
| `handoff` | `working` |
| `task_state` | `working` |
| `decision` | `archival` |
| `code_note` | `archival` |
| `bug` | `archival` |
| `evidence` | `archival` |
| `task_lesson` | `reflective` |
| `reflection` | `reflective` |

### Taxonomy

Active kinds:

```text
constraint
preference
decision
code_note
handoff
bug
environment
procedure
evidence
task_state
task_lesson
reflection
```

Deprecated but readable kinds:

```text
task
session
```

Deprecated kinds must remain readable, listable, showable, searchable, and indexable. New creation of deprecated kinds should be rejected by default unless an explicit internal/test escape hatch is added. Do not expose deprecated-kind creation as normal user-facing behavior.

### Placement policy by kind

Define placement policy constants in `agent_memory/note.py` or `agent_memory/classify.py` so PLAN-7 can consume them without duplicating logic.

| Kind | Placement policy |
|---|---|
| `constraint` | deterministic global default unless explicit project is provided |
| `preference` | deterministic global default unless explicit project is provided |
| `procedure` | deterministic global default unless explicit project is provided or content references one known project |
| `environment` | deterministic global default for OS/device/tooling facts; project if explicit project or repo-specific content |
| `handoff` | project required |
| `task_state` | project required |
| `bug` | project required |
| `evidence` | project required unless explicit global evidence is supported later |
| `decision` | classify when project not explicit |
| `code_note` | classify when project not explicit |
| `task_lesson` | classify with project bias; explicit project preferred |
| `reflection` | classify; if generated from source notes, inherit source project |
| `task` | deprecated readable; new creation rejected by default |
| `session` | deprecated readable; new creation rejected by default |

---

## SQLite Index Requirements

SQLite is derived from Markdown, but later plans need fast filtering. Add columns to the main `notes` table or equivalent derived table for:

```text
schema_version INTEGER
kind TEXT
project TEXT
title TEXT
created_at TEXT
created_by TEXT
updated_at TEXT
updated_by TEXT
status TEXT
layer TEXT
source_agent TEXT
session_id TEXT
confidence REAL
review_required INTEGER
classification_reason TEXT
classification_method TEXT
content_hash TEXT
body_hash TEXT
path TEXT
```

Add a derived relationship table now or explicitly create the migration stub for PLAN-10:

```sql
CREATE TABLE IF NOT EXISTS note_links (
    source_note_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_note_id TEXT NOT NULL,
    PRIMARY KEY (source_note_id, relation, target_note_id)
);
```

Valid `relation` values:

```text
related
supersedes
superseded_by
evidence_for
```

`body_hash` must be a hash of normalized Markdown body content without frontmatter. `content_hash` may remain a hash of the full file or canonical serialized note.

---

## Task 1: Update taxonomy constants and `Note` dataclass

**Files:**
- Modify: `agent_memory/note.py`
- Modify: `tests/note_test.py`

- [ ] Add constants for active kinds, deprecated kinds, and all readable kinds.
- [ ] Add constants for valid lifecycle statuses: `active`, `superseded`, `archived`, `draft`.
- [ ] Add constants for valid layers: `core`, `working`, `archival`, `reflective`.
- [ ] Add constants or helper mapping for default layer by kind.
- [ ] Add constants or helper mapping for placement policy by kind.
- [ ] Extend `Note` with V2 metadata fields while keeping V1 readback ergonomic.
- [ ] Make relationship fields list-based only: `related`, `supersedes`, `superseded_by`, `evidence_for`.
- [ ] Add optional `files: list[str]` for changed-file/context retrieval support.
- [ ] Add tests that kind sets are disjoint and all readable kinds have a defined layer/placement policy or explicit deprecated behavior.

---

## Task 2: Add V1/V2 frontmatter schema helpers

**Files:**
- Modify: `agent_memory/frontmatter.py`
- Modify: `tests/frontmatter_test.py`

- [ ] Introduce `CURRENT_SCHEMA_VERSION = 2`.
- [ ] Preserve V1 required-field support for existing notes.
- [ ] Add V2 required and optional field constants.
- [ ] Ensure `write_frontmatter()` serializes fields deterministically.
- [ ] Ensure list fields serialize as YAML lists even when empty.
- [ ] Ensure `review_required` serializes as a boolean, not a status string.
- [ ] Add tests for V1 read compatibility and V2 write/read roundtrip.
- [ ] Add tests for relationship fields as lists.

---

## Task 3: Write V2 notes from `NoteStore`

**Files:**
- Modify: `agent_memory/store.py`
- Modify: `tests/store_test.py`

- [ ] Update `create_note()` to write `schema_version: 2` by default.
- [ ] Store `title` in frontmatter while preserving `# <Title>` in the Markdown body.
- [ ] Populate `updated_at` and `updated_by` on create.
- [ ] Default `status` to `active`.
- [ ] Default `review_required` to `false` unless classification/recovery policy says otherwise.
- [ ] Set default `layer` using the kind-to-layer mapping.
- [ ] Populate empty relationship lists consistently if the serializer policy includes empty lists.
- [ ] Keep V1 readback working when metadata fields are absent.
- [ ] Reject new creation of deprecated `task` and `session` kinds by default.
- [ ] Add tests for each new kind and deprecated-kind creation rejection.

---

## Task 4: Add SQLite schema/index migration for V2 metadata

**Files:**
- Modify: `agent_memory/index.py`
- Modify: `tests/index_test.py`
- Modify: `tests/store_test.py`

- [ ] Add index metadata/version tracking if it does not already exist.
- [ ] Add/rebuild SQLite columns required by V2 metadata filtering.
- [ ] Add or stub `note_links` table.
- [ ] Ensure index rebuild reads both V1 and V2 notes.
- [ ] Ensure V1 notes get derived defaults in SQLite without rewriting the Markdown file.
- [ ] Store `content_hash` and `body_hash` separately.
- [ ] Add tests for filtering by `status`, `layer`, `review_required`, and `source_agent` if list/search APIs expose these filters.
- [ ] Add tests for note link indexing from frontmatter relationship fields.

---

## Task 5: Decide minimal CLI exposure

**Files:**
- Modify only if needed: `agent_memory/cli.py`
- Modify only if needed: `tests/cli_test.py`

- [ ] Add user-facing flags only where they are needed immediately.
- [ ] Any new user-facing flag must have both a short and long form.
- [ ] Candidate flags: `-s/--status`, `-y/--layer`, `-S/--session-id`, `-A/--source-agent`, `-F/--file`.
- [ ] Do not add migration or compaction commands in this plan.
- [ ] Keep `note list` output compact; detailed metadata can belong to `note show` or a later flag.

---

## Task 6: Update docs and version

**Files:**
- Modify: `docs/PROJECT_STATUS.md`
- Modify: `pyproject.toml`
- Modify: `agent_memory/__init__.py`

- [ ] Mark Schema V2 as complete when implementation and tests pass.
- [ ] Clarify that V2 writes by default and V1 reads remain supported.
- [ ] Clarify that root `HANDOFF.md`, if present in older bundles, is stale and not authoritative.
- [ ] Bump MINOR version because this is a backward-compatible feature and metadata/index change.

---

## Tests to Add

- [ ] V2 required fields serialize and parse deterministically.
- [ ] V1 notes parse, show, list, search, and rebuild-index without being rewritten.
- [ ] Deprecated `task` and `session` notes are readable but not creatable by default.
- [ ] All active kinds have default layer and placement policy.
- [ ] `review_required` is a boolean independent of `status`.
- [ ] Relationship fields must be lists.
- [ ] SQLite index contains V2 metadata columns.
- [ ] `body_hash` ignores frontmatter-only changes where intended.

---

## Validation

Run:

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m pytest tests/ -v --tb=short
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m ruff check agent_memory tests
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m ruff format --check agent_memory tests
```

If Black is installed and still part of the module workflow, also run:

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m black --check --line-length 120 agent_memory tests
```

---

## Definition of Done

- [ ] New active kinds are accepted for V2 note creation.
- [ ] Deprecated `task` and `session` notes remain readable and indexable.
- [ ] Deprecated kinds are not created by normal create APIs/CLI.
- [ ] V2 notes include title, lifecycle, provenance, layer, review, and relationship metadata.
- [ ] `status` and `review_required` have non-overlapping semantics.
- [ ] SQLite index exposes metadata required by later classification, context retrieval, compaction, and handoff plans.
- [ ] V1 notes still parse, index, list, search, and show.
- [ ] Full test suite passes.

---

## Risks, Edge Cases, and Compatibility Notes

- V1 compatibility must be read/index compatibility, not automatic file migration.
- Avoid silently coercing malformed human-edited fields in this plan; PLAN-6 will formalize recovery diagnostics.
- Adding SQLite columns must not make old indexes silently inconsistent. Add a version gate and rebuild path.
- Relationship fields may be absent in existing notes. Treat absent lists as empty lists in memory.
- Do not overexpose metadata flags in CLI until there is a demonstrated use case.
