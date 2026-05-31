# agent_memory Code-Aware Search and Ranking — Revised Implementation Plan

> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve local search quality for code-heavy memory while keeping SQLite FTS5 as the primary index and preserving no-server/local-first behavior.

**Architecture:** Establish a small benchmark baseline before changing FTS behavior, version the derived SQLite index, rebuild FTS objects on tokenizer/index-version changes, sanitize user queries, rank with BM25 column weights, and add targeted identifier support only if token tests prove FTS is insufficient.

**Prerequisites:** PLAN-5 complete. PLAN-6 recommended.

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## File Map

| File | Responsibility |
|---|---|
| `agent_memory/index.py` | FTS schema, versioning, ranking, query sanitization, optional identifier table |
| `agent_memory/store.py` | Search result conversion and optional metadata |
| `agent_memory/cli.py` | Search output ordering/snippet flags if exposed |
| `agent_memory/bench.py` | Small benchmark helper or baseline generator |
| `tests/index_test.py` | Tokenizer, escaping, ranking, rebuild tests |
| `tests/store_test.py` | Store-level search tests |
| `tests/cli_test.py` | CLI search behavior tests |
| `tests/bench_test.py` | Small benchmark helper smoke tests if created |
| `docs/PROJECT_STATUS.md` | Status update |
| `pyproject.toml` | Version bump |
| `agent_memory/__init__.py` | Version bump |

---

## Design Rules

### FTS5 remains the default

Do not add a non-stdlib search dependency in this plan. SQLite FTS5 remains the default search engine.

### Establish a baseline before changing FTS behavior

Before changing tokenization/ranking, add a small benchmark helper or script that can create synthetic notes in a temp directory and measure:

- note creation,
- index rebuild,
- common searches,
- code-heavy searches,
- list/filter queries.

Do not run large benchmarks in normal tests.

### Rebuild FTS objects when index version changes

Changing tokenizer options requires dropping/recreating the FTS virtual table. `CREATE VIRTUAL TABLE IF NOT EXISTS` is not enough.

On index-version mismatch:

```text
1. Close active cursors/transactions safely.
2. Drop FTS triggers if present.
3. Drop `notes_fts`.
4. Recreate `notes_fts` with the new tokenizer/schema.
5. Recreate triggers if used.
6. Rebuild FTS rows from the canonical `notes` table or Markdown scan.
7. Update index metadata version.
```

### Search queries must be sanitized

Raw user search strings may contain quotes, dashes, paths, backslashes, dots, colons, or slashes. Search must not crash with SQLite syntax errors.

Queries that must be tested:

```text
--flag
-k
path/to/file.py
agent_memory/store.py
foo.bar
foo_bar
foo-bar
C:\Users\Max\file.py
"unterminated quote
repo:agent_memory
```

If the query cannot be safely expressed as an FTS `MATCH` query, fallback to a quoted-token query or LIKE-based search instead of raising.

### BM25 weighting

Title matches should rank above body-only matches. Use column weights if the FTS table has separate title/body/tag/search fields.

Example target behavior:

```sql
ORDER BY bm25(notes_fts, 5.0, 1.0, 2.0)
```

Tune the exact column count/weights to the implemented FTS schema.

### Search text size

The draft plan relied on body excerpts. For handoff/debug/code notes, 2000 characters may miss important identifiers. Add a derived `search_text` strategy:

- Prefer indexing `title`, `tags`, and a capped normalized body/search field.
- If capping body text, set the cap deliberately and document it.
- Consider a higher cap than 2000 characters for handoff and code notes if tests show missed identifiers.

---

## Task 1: Add baseline benchmark helper

**Files:**
- Create: `agent_memory/bench.py` or module-local benchmark script
- Create: `tests/bench_test.py` if using importable helper functions

- [ ] Generate synthetic notes in `tempfile.TemporaryDirectory()` by default.
- [ ] Support explicit root override with both `-r/--root` if exposed as CLI/module command.
- [ ] Support note count with both `-n/--notes` if exposed as CLI/module command.
- [ ] Generate mixed natural-language, Markdown, code identifiers, paths, CLI flags, and stack-trace-like content.
- [ ] Measure create, rebuild, list, and search timings.
- [ ] Output JSON Lines or a stable table suitable for future comparison.
- [ ] Add only small smoke tests; do not run 1K/10K/50K tests in normal pytest.

---

## Task 2: Add index versioning and FTS rebuild semantics

**Files:**
- Modify: `agent_memory/index.py`
- Modify: `tests/index_test.py`

- [ ] Add an index metadata table if not already present.
- [ ] Define an explicit `INDEX_VERSION` constant.
- [ ] Detect old or missing index versions.
- [ ] On version mismatch, drop/recreate FTS objects and rebuild rows.
- [ ] Ensure Markdown files remain the source of truth.
- [ ] Add tests that simulate an old index version and verify rebuild creates the new FTS table.
- [ ] Add tests proving `CREATE VIRTUAL TABLE IF NOT EXISTS` does not leave old tokenizer behavior in place.

---

## Task 3: Configure code-aware FTS5 tokenizer

**Files:**
- Modify: `agent_memory/index.py`
- Modify: `tests/index_test.py`

- [ ] Use `unicode61` with token characters that preserve useful code identifiers.
- [ ] Prioritize underscores and selected punctuation relevant to module names, paths, and flags.
- [ ] Avoid stemming as the default.
- [ ] Do not make trigram indexing the default for full note body content.
- [ ] Add tokenizer/search tests for `snake_case`, `kebab-case`, CLI flags, file paths, module names, stack trace fragments, and Python import paths.

---

## Task 4: Add safe query construction and fallback behavior

**Files:**
- Modify: `agent_memory/index.py`
- Modify: `tests/index_test.py`
- Modify: `tests/store_test.py`

- [ ] Add a helper that converts raw user search text into a safe FTS query.
- [ ] Catch SQLite FTS syntax errors and fallback to safe quoted query or LIKE fallback.
- [ ] Add tests for problematic raw queries listed above.
- [ ] Ensure searches never crash on malformed quotes, Windows paths, flags, or punctuation-heavy identifiers.
- [ ] Ensure empty/whitespace-only query behavior remains documented and tested.

---

## Task 5: Add ranked search results

**Files:**
- Modify: `agent_memory/index.py`
- Modify: `agent_memory/store.py`
- Modify: `tests/index_test.py`

- [ ] Order FTS results by BM25 rank.
- [ ] Apply title/body/tag/search-text column weights.
- [ ] Consider returning internal rank/snippet metadata without breaking the public `search()` API.
- [ ] Preserve LIKE fallback behavior when FTS5 is unavailable.
- [ ] Add tests proving exact title matches rank above body-only matches.
- [ ] Add tests proving project/status/layer filters still apply before or after ranking as intended.

---

## Task 6: Add optional snippet output

**Files:**
- Modify only if useful: `agent_memory/index.py`
- Modify only if useful: `agent_memory/cli.py`
- Modify only if useful: `tests/cli_test.py`

- [ ] Decide whether snippets belong in the public API or only CLI output.
- [ ] If adding a CLI flag, use both short and long forms, such as `-S/--show-snippets`.
- [ ] Ensure snippets do not expose malformed terminal control sequences without escaping if logs/code are indexed.
- [ ] Add tests for snippets that do not break existing search output expectations.

---

## Task 7: Evaluate targeted partial identifier search

**Files:**
- Maybe modify: `agent_memory/index.py`
- Maybe modify: `tests/index_test.py`

- [ ] First add failing tests for realistic partial identifier misses.
- [ ] If FTS token search cannot satisfy them, add a targeted secondary identifier table instead of trigram-indexing all body text.
- [ ] Candidate table: `identifier_terms(note_id TEXT, term TEXT, source TEXT)`.
- [ ] Extract identifiers from title, tags, file paths, module paths, CLI flags, and optionally code-like tokens in body.
- [ ] Use this only as a secondary recall layer; keep FTS5 as primary.
- [ ] Do not add this table if tests show FTS tokenization is sufficient.

---

## Task 8: Update docs and version

**Files:**
- Modify: `docs/PROJECT_STATUS.md`
- Modify: `pyproject.toml`
- Modify: `agent_memory/__init__.py`

- [ ] Document tokenizer/ranking behavior.
- [ ] Document query escaping/fallback behavior.
- [ ] Document benchmark helper usage.
- [ ] Bump MINOR version if API/CLI behavior changes; PATCH if internal ranking only.

---

## Tests to Add

- [ ] Benchmark helper small smoke test.
- [ ] Index metadata version initialization.
- [ ] Old-index version rebuild drops/recreates FTS objects.
- [ ] Code-aware token search for identifiers and paths.
- [ ] Malformed/punctuation-heavy raw queries do not crash.
- [ ] BM25 title weighting ranks title matches above body-only matches.
- [ ] LIKE fallback still works.
- [ ] Optional identifier table only exists/works if implemented.

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

Run a small benchmark manually after implementation. Use a temp directory by default or an explicit root:

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m agent_memory.bench -n 1000
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m agent_memory.bench -n 1000 -r /tmp/agent-memory-bench
```

---

## Definition of Done

- [ ] Baseline benchmark helper exists and is documented.
- [ ] Code identifiers are searchable as useful tokens.
- [ ] Search queries with paths/flags/punctuation do not crash.
- [ ] Search results are deterministically ranked.
- [ ] Old indexes rebuild cleanly when tokenizer/index version changes.
- [ ] LIKE fallback still works.
- [ ] No non-stdlib search engine dependency is introduced.

---

## Risks, Edge Cases, and Compatibility Notes

- Changing FTS tokenizer requires real FTS table rebuild, not just schema constant changes.
- Trigram indexing all note bodies can increase index size and write cost; avoid by default.
- User queries are untrusted text and should not be interpolated into SQL strings.
- Windows paths and CLI flags are common in this project and must be first-class test cases.
- Do not make performance tests flaky by asserting strict timings in normal pytest.
