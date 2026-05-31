# agent_memory Frontmatter Hardening — Revised Implementation Plan

> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make human-edited Markdown notes safe to validate, index, and recover from when YAML frontmatter is malformed, ambiguous, missing fields, or inconsistent with the filesystem path.

**Architecture:** Markdown plus YAML frontmatter remains canonical. Parsing gains a safe result object that preserves raw text and actionable diagnostics. Verification becomes per-file and layout-aware. Index rebuild must not hide duplicate IDs or malformed frontmatter.

**Prerequisites:** PLAN-5 complete.

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## File Map

| File | Responsibility |
|---|---|
| `agent_memory/frontmatter.py` | Parse, safe-parse, write, validate, and recover frontmatter |
| `agent_memory/store.py` | Verify path/schema consistency, duplicate IDs, and rebuild behavior |
| `agent_memory/index.py` | Rebuild interactions with validation and duplicate detection |
| `agent_memory/cli.py` | Surface validation diagnostics through verify/status commands |
| `tests/frontmatter_test.py` | Parser and validation unit tests |
| `tests/store_test.py` | Verify/rebuild integration tests |
| `tests/index_test.py` | Rebuild behavior with invalid files and duplicate IDs |
| `tests/cli_test.py` | CLI diagnostics tests |
| `docs/PROJECT_STATUS.md` | Status update |
| `pyproject.toml` | Version bump |
| `agent_memory/__init__.py` | Version bump |

---

## Design Rules

### Use `ValidationIssue`, not `ValidationError`

Avoid a generic `ValidationError` name because it is easy to confuse with thrown exceptions or validation-library errors.

Recommended shape:

```python
@dataclass(frozen=True)
class ValidationIssue:
    path: Path | None
    field: str | None
    code: str
    message: str
    severity: Literal["error", "warning"]
```

### Add a safe parser result

Keep any existing strict/backward-compatible parser if needed, but add a safe parser for verification and rebuild workflows:

```python
@dataclass(frozen=True)
class FrontmatterParseResult:
    metadata: dict[str, Any]
    body: str
    issues: list[ValidationIssue]
    raw_frontmatter: str | None
    has_frontmatter: bool
```

Recommended function split:

```python
parse_frontmatter(text: str) -> tuple[dict[str, Any], str]
parse_frontmatter_safe(text: str, path: Path | None = None) -> FrontmatterParseResult
```

`parse_frontmatter()` may continue to support current callers. New validation, verify, and rebuild logic should use `parse_frontmatter_safe()`.

### Reject vs normalize policy

Do not silently coerce semantically important fields. Human editability is valuable, but agents must not quietly reinterpret corrupted metadata.

| Field | Required type | Invalid type behavior |
|---|---|---|
| `id` | string | error; do not coerce int to string |
| `schema_version` | int | error if non-int |
| `kind` | string | error if non-string or unknown |
| `project` | string | error if non-string |
| `title` | string | error for V2 if non-string |
| `created_at` | string | error if missing/non-string |
| `created_by` | string | error if missing/non-string |
| `updated_at` | string | error for V2 if missing/non-string |
| `updated_by` | string | error for V2 if missing/non-string |
| `status` | string | error if unknown lifecycle status |
| `layer` | string | warning if missing, error if invalid value |
| `tags` | list[string] | error if scalar or mixed-type list |
| `review_required` | bool | error if non-bool |
| `confidence` | float/int | error if non-number or outside 0.0-1.0 |
| relationship fields | list[string] | error if scalar or mixed-type list |
| `files` | list[string] | error if scalar or mixed-type list |

Safe normalization allowed:

- strip UTF-8 BOM before parsing,
- treat absent optional list fields as empty lists in memory,
- treat absent optional booleans as documented defaults in memory,
- normalize line endings for body hashing only, not file rewriting.

### Layout-aware path validation

Do not hardcode parent/grandparent assumptions in multiple places. Create one resolver used by verify and rebuild:

```python
@dataclass(frozen=True)
class NotePathMetadata:
    scope: Literal["global", "project", "unknown"]
    project: str | None
    kind: str | None
    layout: Literal["v1", "sharded", "unknown"]
```

```python
resolve_note_path_metadata(path: Path, root: Path) -> NotePathMetadata
```

This prevents PLAN-12 path sharding from breaking PLAN-6 validation.

---

## Task 1: Add structured validation diagnostics

**Files:**
- Modify: `agent_memory/frontmatter.py`
- Modify: `tests/frontmatter_test.py`

- [ ] Add `ValidationIssue` with `path`, `field`, `code`, `message`, and `severity`.
- [ ] Add stable issue code constants or documented strings.
- [ ] Validate required fields by schema version.
- [ ] Validate field types according to the reject-vs-normalize policy.
- [ ] Validate enum fields: `kind`, `status`, and `layer`.
- [ ] Validate relationship fields as `list[str]` only.
- [ ] Validate `confidence` range when present.
- [ ] Add tests for typed YAML scalars: `yes`, `no`, `null`, numeric IDs, non-list tags, scalar relationship fields, mixed-type lists.

---

## Task 2: Harden parsing and recovery

**Files:**
- Modify: `agent_memory/frontmatter.py`
- Modify: `tests/frontmatter_test.py`

- [ ] Add `FrontmatterParseResult`.
- [ ] Add `parse_frontmatter_safe()`.
- [ ] Strip a UTF-8 BOM before frontmatter matching.
- [ ] Catch YAML parse errors and return structured parse failures without discarding body text.
- [ ] Preserve `raw_frontmatter` for diagnostics and possible manual recovery.
- [ ] Preserve raw body text even when metadata parsing fails.
- [ ] Add tests for malformed YAML, missing closing delimiter, no frontmatter, BOM-prefixed files, and YAML document markers inside body text.

---

## Task 3: Add layout resolver and per-file verification

**Files:**
- Modify: `agent_memory/store.py`
- Modify: `tests/store_test.py`

- [ ] Add `resolve_note_path_metadata()` or equivalent layout resolver.
- [ ] Make `verify()` check every note independently.
- [ ] Ensure one invalid file does not suppress checks for later files.
- [ ] Validate `kind` against path layout when layout is known.
- [ ] Validate `project` against `global/` or `projects/<project>/` when layout is known.
- [ ] Report unknown/unsupported layouts as warnings or errors according to severity policy.
- [ ] Add tests for global notes, project notes, mismatched kind, mismatched project, unknown layout, and future sharded-layout compatibility stubs.

---

## Task 4: Detect duplicate IDs before index upsert

**Files:**
- Modify: `agent_memory/store.py`
- Modify: `agent_memory/index.py`
- Modify: `tests/store_test.py`
- Modify: `tests/index_test.py`

- [ ] Ensure duplicate IDs are detected by scanning parsed notes before index upsert collapses rows.
- [ ] Report every duplicate path pair/group.
- [ ] Make `verify()` fail on duplicate IDs.
- [ ] Decide rebuild behavior when duplicates are present: recommended behavior is to abort rebuild and report duplicate diagnostics.
- [ ] Add tests proving duplicate IDs are not hidden by SQLite primary-key upsert behavior.

---

## Task 5: Improve CLI diagnostics

**Files:**
- Modify: `agent_memory/cli.py`
- Modify: `tests/cli_test.py`

- [ ] Add or refine `agent-memory verify` if it does not already exist.
- [ ] Every new flag must have a short and long form.
- [ ] Recommended flags: `-r/--root`, `-v/--verbose`, `-j/--json`, `-W/--warnings-as-errors`.
- [ ] Ensure `index status` reports validation issue counts clearly.
- [ ] Ensure detailed issue output includes path, field, issue code, severity, and actionable message.
- [ ] Keep exit behavior predictable: status can exit 0; explicit verify exits nonzero on errors.

---

## Task 6: Update docs and version

**Files:**
- Modify: `docs/PROJECT_STATUS.md`
- Modify: `pyproject.toml`
- Modify: `agent_memory/__init__.py`

- [ ] Document hardened validation and recovery behavior.
- [ ] Document the reject-vs-normalize policy.
- [ ] Bump MINOR version if CLI/API behavior is added; otherwise PATCH for internal validation hardening.

---

## Tests to Add

- [ ] `parse_frontmatter_safe()` returns body text when YAML is malformed.
- [ ] BOM-prefixed files parse correctly.
- [ ] Missing closing frontmatter delimiter reports a structured error.
- [ ] No-frontmatter Markdown reports a structured error without losing content.
- [ ] Wrong scalar types produce errors rather than silent coercion.
- [ ] Duplicate IDs are detected before indexing.
- [ ] Path/project/kind mismatches are reported per file.
- [ ] Explicit verify exits nonzero on errors.
- [ ] `index status` reports issue counts without surprising nonzero exits.

---

## Validation

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m pytest tests/ -v --tb=short
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m ruff check agent_memory tests
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m ruff format --check agent_memory tests
```

---

## Definition of Done

- [ ] Malformed frontmatter is reported, not silently skipped.
- [ ] YAML scalar ambiguity is caught for fields that must remain strings/lists/booleans.
- [ ] Duplicate note IDs are detected before index rebuild/upsert.
- [ ] Path/project/kind mismatches are reported independently for every file.
- [ ] Existing valid V1 and V2 notes still read and index.
- [ ] CLI diagnostics are actionable and test-covered.

---

## Risks, Edge Cases, and Compatibility Notes

- Avoid breaking existing code that expects `parse_frontmatter()` to return `(metadata, body)`.
- Avoid rewriting human-edited files during validation unless a future explicit repair command is introduced.
- Path validation must tolerate future sharding layouts by using a resolver abstraction.
- Do not let index rebuild hide duplicate IDs.
- Avoid logging raw note bodies in diagnostics; paths and issue messages should be enough.
