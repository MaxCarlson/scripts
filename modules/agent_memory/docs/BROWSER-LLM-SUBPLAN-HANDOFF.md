# Browser LLM Handoff — Generate agent_memory Research-Aligned Subplans

> Use this document as the prompt/context package for a web-based LLM that does
> not have local filesystem access. The goal is to have that LLM generate
> detailed implementation subplans for `agent_memory`, using the deep research
> response and current implementation as context.

---

## Prompt to Paste Into the Browser LLM

You previously produced a deep research response for my local-first AI agent
memory system. I now need you to turn that research into detailed implementation
subplans for the `agent_memory` Python module.

You do **not** have repository access, so I am attaching one or more
consolidated repository/module bundles produced by `zip_for_llms`. Please read
the attached bundle files and generate implementation plans only. Do not write
code.

The output should be a set of Markdown plan documents, one per phase, matching
the style of the existing `PLAN-1` through `PLAN-4` docs. Each plan should be
specific enough that a coding agent with repo access can implement it without
having to infer architecture.

Create plans for these phases:

1. `PLAN-5-SCHEMA-V2.md`
   Add frontmatter schema V2, lifecycle/provenance fields, expanded taxonomy,
   and V1 read compatibility.

2. `PLAN-6-FRONTMATTER-HARDENING.md`
   Harden YAML/frontmatter parsing, validation, recovery, duplicate ID checks,
   and verify diagnostics.

3. `PLAN-7-STRUCTURED-CLASSIFY.md`
   Replace plain-text LLM classification with structured decisions, confidence,
   reason codes, deterministic pre-rules, and user-confirmation policy.

4. `PLAN-8-SEARCH-RANKING.md`
   Improve SQLite FTS5 search with code-aware tokenization, rank ordering, and
   targeted identifier search if needed.

5. `PLAN-9-CONTEXT-RETRIEVAL.md`
   Add an explicit context retrieval API and optional CLI for ordering memories
   for agent session startup.

6. `PLAN-10-COMPACTION.md`
   Add deterministic compaction planning, supersession metadata, reflective
   notes, dry-run/apply workflows, and review-required behavior.

7. `PLAN-11-HANDOFF-SCHEMA.md`
   Standardize handoff note schema and acknowledgment shape for later
   `agent_sync` integration.

8. `PLAN-12-PERFORMANCE-ERGONOMICS.md`
   Add performance docs, benchmark tooling, and scaling/path-layout guidance.

For each plan, include:

- Title and one-paragraph goal.
- Architecture summary.
- Prerequisites and working directory.
- File map.
- Ordered tasks with checkbox syntax.
- Concrete files to create/modify.
- Test cases to add.
- CLI/API changes, if any.
- Version bump guidance according to the repository rules.
- Validation commands.
- Definition of done.
- Risks, edge cases, and compatibility notes.

Keep each plan practical and implementable. Prefer explicit task sequencing over
high-level strategy. Keep dependencies between plans clear.

Important repository constraints:

- Python 3.11+.
- `uv` is the package manager, but local tests are usually run with
  `/home/mcarls/scripts/.venv/bin/python -m pytest ...`.
- Cross-platform support matters: WSL2 Ubuntu, Windows 11, Termux Android.
- Source files should prefer `pathlib.Path`.
- Library code uses `logging`, not `print`.
- CLI entry points may print.
- Every user-facing CLI argument must have both a short and long form.
- Tests use filenames like `tests/module_name_test.py`, not `test_module.py`.
- Use `tmp_path` for filesystem tests.
- No live external service calls in tests.
- Bump module version for every module change:
  - MAJOR for entry point changes.
  - MINOR for backward-compatible user-facing features or dependency/metadata
    changes.
  - PATCH for bug fixes, refactors, docs, or tests only.
- Update both `pyproject.toml` and `agent_memory/__init__.py` when bumping
  `agent_memory`.
- Run `pytest`, `ruff check`, and formatting checks before reporting complete.

Please produce the plan documents as separate Markdown sections with filenames
as headings. Do not assume any files beyond the attached bundles.

---

## Current Repository and Module Context

Repository root:

```text
/home/mcarls/scripts
```

Module root:

```text
/home/mcarls/scripts/modules/agent_memory
```

Implemented baseline:

- PLAN-1 `llm_local`: complete.
- PLAN-2 `agent_memory` core: complete.
- PLAN-3 CLI: complete.
- PLAN-4 LLM placement classification: complete.

Current test status after PLAN-4:

```text
91 passed
```

Current `agent_memory` version after PLAN-4:

```text
0.3.0
```

Current high-level architecture:

- Markdown files with YAML frontmatter are canonical source of truth.
- SQLite FTS5 index is a rebuildable derived cache.
- Notes live under a configurable root:
  - default: `~/scripts/modules/agent_memory/notes/`
  - env override: `AGENT_MEMORY_ROOT`
  - CLI override: `-r/--root`
- `llm_local` is a stdlib-only client for LM Studio/OpenAI-compatible local
  chat completions.
- `agent_memory.classify` uses deterministic placement rules first, then local
  LLM classification for ambiguous note kinds.

Current note kinds:

```text
constraint
preference
decision
code_note
handoff
task
bug
session
```

Current V1 frontmatter fields:

```yaml
id: string
schema_version: 1
kind: string
project: string
created_at: UTC timestamp
created_by: string
tags: list[string]
```

Current implemented CLI commands:

```bash
agent-memory note create
agent-memory note list
agent-memory note show
agent-memory note edit
agent-memory search
agent-memory index rebuild
agent-memory index status
```

---

## Preferred Attachment Strategy: zip_for_llms Bundles

Use `zip_for_llms` to collapse the relevant module folders into one text bundle
per module/folder. This is better than attaching many individual files because
the browser LLM can see paths, code, tests, docs, and plan style in one
continuous artifact.

On WSL/Linux, the examples below use:

```bash
python pyscripts/zip_for_llms.py ...
```

On Windows, use the equivalent wrapper:

```powershell
zip_for_llms.cmd ...
```

or call the Python script directly if the wrapper is not on `PATH`.

Run commands from the repo root:

```bash
cd /home/mcarls/scripts
```

### Bundle 1: agent_memory full planning context

This should be the primary attachment. It includes module code, tests, design
docs, research docs, and existing plans.

```bash
python pyscripts/zip_for_llms.py modules/agent_memory \
  --file-mode \
  --output /tmp/agent_memory_for_subplans \
  --preset python \
  --exclude-dir .venv \
  --exclude-dir .cache \
  --exclude-dir .pytest_cache \
  --exclude-dir __pycache__ \
  --exclude-dir .mypy_cache \
  --exclude-dir .ruff_cache \
  --exclude-dir .index \
  --exclude-dir notes \
  --exclude-file uv.lock \
  --exclude-ext .pyc
```

Attach:

```text
/tmp/agent_memory_for_subplans.txt
```

If the generated text file is too large for the browser LLM, create a smaller
docs-only bundle plus a code-only bundle:

```bash
python pyscripts/zip_for_llms.py modules/agent_memory/docs \
  --file-mode \
  --output /tmp/agent_memory_docs_for_subplans \
  --exclude-dir .pytest_cache \
  --exclude-dir __pycache__

python pyscripts/zip_for_llms.py modules/agent_memory/agent_memory \
  --file-mode \
  --output /tmp/agent_memory_code_for_subplans \
  --preset python \
  --exclude-dir __pycache__ \
  --exclude-ext .pyc

python pyscripts/zip_for_llms.py modules/agent_memory/tests \
  --file-mode \
  --output /tmp/agent_memory_tests_for_subplans \
  --preset python \
  --exclude-dir __pycache__ \
  --exclude-ext .pyc
```

Attach:

```text
/tmp/agent_memory_docs_for_subplans.txt
/tmp/agent_memory_code_for_subplans.txt
/tmp/agent_memory_tests_for_subplans.txt
```

### Bundle 2: llm_local focused context

Attach this only if asking the browser LLM to write
`PLAN-7-STRUCTURED-CLASSIFY.md`, because that plan may need to extend
`llm_local.complete()` for structured output.

```bash
python pyscripts/zip_for_llms.py modules/llm_local \
  --file-mode \
  --output /tmp/llm_local_for_structured_classify \
  --preset python \
  --exclude-dir .venv \
  --exclude-dir .cache \
  --exclude-dir .pytest_cache \
  --exclude-dir __pycache__ \
  --exclude-dir .mypy_cache \
  --exclude-dir .ruff_cache \
  --exclude-file uv.lock \
  --exclude-ext .pyc
```

Attach:

```text
/tmp/llm_local_for_structured_classify.txt
```

### Bundle 3: repository standards

Attach repository standards separately if the primary bundle does not include
the repo root files.

```bash
python pyscripts/zip_for_llms.py . \
  --file-mode \
  --output /tmp/scripts_standards_for_subplans \
  --include-file AGENTS.md \
  --include-file MODULE_STANDARDS.md \
  --remove-pattern "*" \
  --keep-pattern "AGENTS.md" \
  --keep-pattern "MODULE_STANDARDS.md"
```

If that include/keep combination does not produce the expected output, attach
these two files manually:

```text
AGENTS.md
MODULE_STANDARDS.md
```

### Bundle hygiene

Exclude these unless explicitly needed:

- `.venv/`
- `.cache/`
- `.pytest_cache/`
- `__pycache__/`
- `.mypy_cache/`
- `.ruff_cache/`
- `.index/`
- `notes/`
- `uv.lock`
- `*.pyc`

Do include:

- `agent_memory/` package code
- `tests/`
- `docs/design/`
- `docs/plans/PLAN-1` through `PLAN-4`
- `docs/DEEP-RESEARCH-REQUEST.md`
- `docs/DEEP-RESEARCH-REQUEST-RESPONSE.md`
- `docs/PROJECT_STATUS.md`
- `pyproject.toml`

---

## Manual Attachment Fallback

If `zip_for_llms` is unavailable, attach these files manually.

### Documents to attach

Attach these documents first. They give the browser LLM the design history and
research recommendations.

### Required design and research docs

- `modules/agent_memory/docs/DEEP-RESEARCH-REQUEST.md`
- `modules/agent_memory/docs/DEEP-RESEARCH-REQUEST-RESPONSE.md`
- `modules/agent_memory/docs/design/agent-memory-design.md`
- `modules/agent_memory/docs/design/agent-memory-research-alignment-plan.md`
- `modules/agent_memory/docs/PROJECT_STATUS.md`

### Existing implementation plans

Attach these so the browser LLM can mirror format and level of detail:

- `modules/agent_memory/docs/plans/PLAN-1-LLM-LOCAL.md`
- `modules/agent_memory/docs/plans/PLAN-2-CORE.md`
- `modules/agent_memory/docs/plans/PLAN-3-CLI.md`
- `modules/agent_memory/docs/plans/PLAN-4-CLASSIFY.md`

### Repository standards

Attach:

- `AGENTS.md`
- `MODULE_STANDARDS.md`

The plan writer should especially follow:

- version bump semantics
- CLI short+long flag requirement
- pytest naming conventions
- module-local temp/test conventions
- cross-platform requirements

---

## Code Files to Attach

Attach these code files so the browser LLM can plan against the real current
implementation, not an abstract design.

### agent_memory package code

- `modules/agent_memory/agent_memory/__init__.py`
- `modules/agent_memory/agent_memory/note.py`
- `modules/agent_memory/agent_memory/frontmatter.py`
- `modules/agent_memory/agent_memory/naming.py`
- `modules/agent_memory/agent_memory/index.py`
- `modules/agent_memory/agent_memory/store.py`
- `modules/agent_memory/agent_memory/classify.py`
- `modules/agent_memory/agent_memory/cli.py`

### agent_memory packaging

- `modules/agent_memory/pyproject.toml`

### agent_memory tests

- `modules/agent_memory/tests/conftest.py`
- `modules/agent_memory/tests/note_test.py`
- `modules/agent_memory/tests/frontmatter_test.py`
- `modules/agent_memory/tests/naming_test.py`
- `modules/agent_memory/tests/index_test.py`
- `modules/agent_memory/tests/store_test.py`
- `modules/agent_memory/tests/classify_test.py`
- `modules/agent_memory/tests/cli_test.py`

### llm_local code

Attach these only for `PLAN-7-STRUCTURED-CLASSIFY.md`, because structured
classification may require extending `llm_local.complete()`:

- `modules/llm_local/pyproject.toml`
- `modules/llm_local/src/llm_local/__init__.py`
- `modules/llm_local/src/llm_local/client.py`
- `modules/llm_local/tests/llm_local_test.py`

---

## Current Implementation Summary by File

Use this if attachment count is limited, but attaching the files above is
preferred.

### `agent_memory/note.py`

Defines:

- `VALID_KINDS`
- `GLOBAL_DEFAULT_KINDS`
- `PROJECT_REQUIRED_KINDS`
- `LLM_CLASSIFY_KINDS`
- `Note` dataclass

Current kind grouping:

- global default: `constraint`, `preference`
- project required: `handoff`, `task`, `bug`
- LLM classified: `decision`, `code_note`, `session`

### `agent_memory/frontmatter.py`

Currently:

- parses YAML frontmatter with a regex
- writes YAML with `yaml.dump`
- validates only missing required V1 fields

Known limitations:

- no type validation
- no structured diagnostics
- no schema migration helpers
- no duplicate ID detection
- no BOM handling
- no YAML scalar ambiguity handling

### `agent_memory/index.py`

Currently:

- SQLite tables: `notes`, `note_tags`
- FTS5 virtual table: `notes_fts`
- triggers keep FTS table in sync
- `search()` uses FTS5 when available and LIKE fallback otherwise
- no rank ordering, snippets, tokenizer customization, or index version table

### `agent_memory/store.py`

Currently:

- creates notes
- reads notes
- lists notes
- searches notes
- rebuilds SQLite index from Markdown files
- verifies frontmatter and kind/path mismatches

Known limitations:

- writes schema version 1
- title is stored only as the Markdown `# H1`, not frontmatter
- no lifecycle/provenance fields
- no metadata update helper
- no context retrieval API
- no compaction/supersession API

### `agent_memory/classify.py`

Currently:

- imports `llm_local.complete` as `_llm_complete` when available
- defines `PlacementError`
- defines `determine_project()`
- deterministic rules:
  - explicit project wins
  - `constraint` and `preference` go global
  - `handoff`, `task`, `bug` require project
  - ambiguous kinds default global unless `auto_classify=True`
- LLM response is plain text: `global` or project slug
- interactive fallback exists when LLM is unavailable and stdin is a TTY

Known limitations:

- no structured JSON classification
- no confidence score
- no reason code
- no known-project list in prompt
- no few-shot examples
- no threshold policy

### `agent_memory/cli.py`

Currently:

- top-level `-r/--root`
- `note create/list/show/edit`
- `search`
- `index rebuild/status`

Important CLI constraint:

- every new user-facing argument must have a short and long form

### `llm_local/client.py`

Currently:

- stdlib-only HTTP client
- posts to OpenAI-compatible `/chat/completions`
- accepts prompt, model, URL, timeout, optional system message
- returns response text or `None`
- catches all network/response errors

Potential future change:

- add optional structured-output/response-format support only if needed for
  structured classification

---

## Research Recommendations to Preserve

The plan documents should reflect these conclusions from the research response:

- Keep Markdown plus YAML frontmatter as canonical source format.
- Keep SQLite FTS5 as primary local lexical search.
- Improve FTS5 tokenizer and ranking before considering another search engine.
- Avoid dense vector retrieval in the immediate `agent_memory` V1 path.
- Treat memory as layered:
  - core
  - archival
  - reflective
- Expand taxonomy:
  - keep `constraint`, `preference`, `decision`, `handoff`, `bug`, `code_note`
  - add `environment`, `procedure`, `evidence`, `task_state`, `task_lesson`,
    `reflection`
  - deprecate `task` and `session`, while preserving read compatibility
- Add lifecycle/provenance metadata:
  - `title`
  - `updated_at`
  - `updated_by`
  - `status`
  - `layer`
  - `source_agent`
  - `session_id`
  - `confidence`
  - `related`
  - `supersedes`
  - `superseded_by`
  - `review_required`
- Harden YAML handling:
  - flat frontmatter
  - strict field types
  - recoverable parse failures
  - duplicate ID detection
  - path/project/kind consistency checks
- Replace plain-text classification with structured output:
  - `scope`
  - `project_slug`
  - `confidence`
  - `reason_code`
  - `needs_user_confirmation`
- Use deterministic rules before LLM calls.
- Use few-shot structured prompts for local model classification.
- Use confidence thresholds:
  - `>= 0.85`: auto-apply
  - `0.60-0.84`: apply only if heuristic agrees
  - `< 0.60`: require confirmation or default safely
- Add context retrieval ordering:
  - stable core constraints first
  - project profile next
  - retrieved evidence near active request
  - current handoff/goal summary near the end
- Add compaction only as deterministic candidate selection followed by optional
  structured LLM recommendations.
- Preserve old notes by marking superseded; do not delete automatically.
- Standardize handoff notes as machine-readable JSON plus Markdown narrative.
- Add a receiving-agent ACK shape, but leave enforcement to `agent_sync`.
- Add performance guidance and benchmark tooling before changing storage layout.

---

## Expected Output Format From Browser LLM

Ask the browser LLM to return the plans in this structure:

```markdown
# PLAN-5-SCHEMA-V2.md

<full plan>

# PLAN-6-FRONTMATTER-HARDENING.md

<full plan>

...
```

Each plan should follow this rough template:

```markdown
# agent_memory <Feature> — Implementation Plan

> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ...
**Architecture:** ...
**Prerequisites:** ...
**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## File Map

| File | Responsibility |
|---|---|
| ... | ... |

---

## Task 1: ...

**Files:**
- Modify: ...
- Create: ...

- [ ] Step...
- [ ] Step...

---

## Validation

```bash
cd /home/mcarls/scripts/modules/agent_memory
/home/mcarls/scripts/.venv/bin/python -m pytest tests/ -v --tb=short
/home/mcarls/scripts/.venv/bin/python -m ruff check agent_memory tests
/home/mcarls/scripts/.venv/bin/python -m ruff format --check agent_memory tests
```

---

## Definition of Done

- [ ] ...
```

---

## Reviewer Instructions for the Browser LLM

Before writing the plans, explicitly compare:

- the original design doc
- the research response
- the current implemented code
- the existing PLAN-1 through PLAN-4 style

Then write the plan documents.

Call out any areas where the research recommendation conflicts with the current
implementation and explain whether the plan should:

- preserve current behavior for compatibility
- add new behavior behind an additive path
- deprecate current behavior
- defer the recommendation

Do not propose a total rewrite. Prefer small, reviewable phases that keep tests
green after each plan.

---

## Notes for the Local Coding Agent After Browser LLM Returns Plans

When the browser LLM returns plans:

1. Save each returned plan under `modules/agent_memory/docs/plans/`.
2. Compare them against `docs/design/agent-memory-research-alignment-plan.md`.
3. Keep the best details from any existing local draft plans if present.
4. Do not implement immediately unless explicitly asked.
5. If implementing later, follow repository versioning and test requirements
   from `MODULE_STANDARDS.md`.
