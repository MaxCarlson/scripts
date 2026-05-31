# Agent Memory — Design Spec

**Date:** 2026-05-31  
**Status:** Approved  
**Author:** Max Carlson + Claude Sonnet 4.6

---

## Purpose

`agent_memory` is a standalone Python module that provides persistent,
human-editable, version-controlled memory for AI agents. It is the Tier 1
(always-works, no-infra) memory layer for the multi-agent system.

Any agent (Claude Code, Codex, Gemini CLI, local workers) running on this
machine can read and write memory notes. Notes are plain Markdown files with
YAML frontmatter. A SQLite index provides fast search and filtering without
requiring a database server.

The heavy Tier 2 memory stack (PostgreSQL + pgvector + embeddings) lives in
`projects/ai-orchestrator/memory/` and ingests from this module's notes.

---

## Module Boundaries

| Module | Responsibility |
|---|---|
| `llm_local` | Thin inference client for `localhost:1234/v1` (LM Studio). Infrastructure only. |
| `agent_memory` | Store, index, retrieve, classify memory notes. Imports `llm_local` for placement decisions. |
| `agent_sync` | Multi-agent coordination. Imports `agent_memory` to write handoff/session notes. |
| `ai-orchestrator` | Imports `agent_memory` via `ingest_notes.py` to push notes into pgvector. |

---

## Storage Layout

```
~/scripts/modules/agent_memory/
  notes/                              ← AGENT_MEMORY_ROOT (configurable)
    global/                           ← cross-project memories
      constraint/
      preference/
      code_note/
    projects/
      <project-slug>/                 ← project-specific memories
        decision/
        handoff/
        task/
        bug/
        session/
        constraint/
        preference/
        code_note/
  .index/
    notes.sqlite3                     ← rebuildable SQLite index (gitignored)
```

**Root configuration:**
- Default: `~/scripts/modules/agent_memory/notes/`
- Override: `AGENT_MEMORY_ROOT` env var
- Per-command: `--root / -r` flag

**Kind taxonomy** — directory name = kind value (singular):

| Kind | Default scope | Description |
|---|---|---|
| `constraint` | global | Hard rules (always inject first) |
| `preference` | global | Soft preferences, coding habits |
| `decision` | project | Architectural/implementation decisions |
| `code_note` | project | Module or design explanations |
| `handoff` | project | Agent-to-agent handoff summaries |
| `task` | project | Task state and progress notes |
| `bug` | project | Known bugs or workarounds |
| `session` | project | Session summaries |

---

## File Naming

```
<UTC-timestamp>_<8-hex-chars>_<slug>.md
```

Example: `20260531T055512Z_a3f9e1b2_use-sqlite-for-memory-index.md`

- Timestamp: `datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")`
- Hex: `secrets.token_hex(4)` — collision-safe, stdlib only
- Slug: `title.lower()` → replace non-alphanum with `-` → truncate at 60 chars

Agent-generated notes always use this format. Human-authored notes may use any
filename ending in `.md` — the index reads frontmatter, not filenames.

---

## Frontmatter Schema (V1 — 7 fields)

```yaml
---
id: 20260531T055512Z_a3f9e1b2
schema_version: 1
kind: decision
project: ai-orchestrator        # "global" for cross-project notes
created_at: 2026-05-31T05:55:12Z
created_by: claude-code
tags:
  - memory
  - sqlite
---
```

**Validation rules:**
- `id` must be unique across all notes
- `kind` must match the parent directory name
- `project` must match the grandparent directory name (or "global")
- All 7 fields required on agent-created notes; human notes may omit `id`
  (index assigns one on first ingest)

**V2 fields (deferred):** `status`, `confidence`, `updated_at`,
`last_modified_by`, `related`, `supersedes`, `superseded_by`, `source`

---

## Note Body Format

```markdown
---
[frontmatter]
---

# <Title>

## Summary

One paragraph.

## Details

Full prose. No length limit.
```

Title in body = note title for display. `body_excerpt` in SQLite index = first
2000 chars of body content (after frontmatter).

---

## Python API

```python
from agent_memory import NoteStore
from pathlib import Path

store = NoteStore()                          # uses AGENT_MEMORY_ROOT
store = NoteStore(root=Path("/custom/path")) # explicit root

# Write
note: Note = store.create_note(
    kind="decision",
    project="ai-orchestrator",   # None → global; triggers LLM classify if ambiguous
    title="Use SQLite for index",
    body="## Summary\n\nUse Markdown...",
    created_by="claude-code",
    tags=["memory", "sqlite"],
    auto_classify=True,          # calls llm_local if project=None and kind is ambiguous
    dry_run=False,
)

# Read
note: Note | None = store.get_note(note_id)
notes: list[Note] = store.list_notes(
    project="ai-orchestrator",   # None = all projects + global
    kind="decision",
    tags=["sqlite"],
    limit=20,
)
results: list[Note] = store.search(
    query="sqlite coordination",
    project="ai-orchestrator",   # None = all
    kind=None,                   # None = all kinds
)

# Index
store.rebuild_index()            # scan all notes/, rebuild notes.sqlite3
store.verify()                   # find path/kind mismatches, missing required fields
```

### `Note` dataclass

```python
@dataclass
class Note:
    id: str
    path: Path                   # absolute path to .md file
    kind: str
    project: str                 # "global" or project slug
    title: str
    body: str                    # full body text
    created_at: str              # ISO 8601 UTC
    created_by: str
    tags: list[str]
    schema_version: int = 1
```

---

## SQLite Index Schema

Location: `<notes-root>/.index/notes.sqlite3`  
Rebuild: `store.rebuild_index()` or `agent-memory index rebuild`  
Source of truth: **Markdown files** (index is a derived cache)

```sql
CREATE TABLE notes (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    project      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    body_excerpt TEXT NOT NULL,   -- first 2000 chars of body
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL,
    content_hash TEXT NOT NULL    -- SHA256 of full file; detect changes
) STRICT;

CREATE TABLE note_tags (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
) STRICT;

-- FTS5 for full-text search; falls back to LIKE on platforms without FTS5
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
    USING fts5(title, body_excerpt, content=notes, content_rowid=rowid);
```

**Cross-platform:** FTS5 is available on CPython on all target platforms
(WSL2, Windows 11, Termux). If `CREATE VIRTUAL TABLE ... USING fts5` fails
(very old SQLite), `search()` falls back to `LIKE` on `title` and `body_excerpt`.

---

## LLM Placement Classification

When `create_note` is called with `project=None` and `kind` is ambiguous
(`decision`, `code_note`, `session`), and `auto_classify=True`:

1. Call `llm_local.complete(prompt)` with a focused, low-token prompt
2. Expect response: `"global"` or `"<project-slug>"`
3. If LLM unreachable: fall back to interactive prompt (or `global` if `--no-interactive`)
4. Log decision: `"Classified as: global (via local LLM). Use --project to override."`

**Placement defaults by kind (no LLM needed):**

| Kind | Auto-placement |
|---|---|
| `constraint`, `preference` | → `global` |
| `handoff`, `task`, `bug`, `session` | → error: `--project` required |
| `decision`, `code_note` | → LLM classify if `project=None` |

**Override always available:** `--project global`, `--project <slug>`, `--no-llm`

---

## CLI Commands

All flags: short + long form. `--root / -r` available on every command.

```bash
# Notes CRUD
agent-memory note create  -k <kind> [-p <project>] -t <title> [-b <body>] \
                          [--tags a,b] [--no-llm] [-n/--dry-run]
agent-memory note list    [-p <project>] [-k <kind>] [--tags a,b] [--limit 20]
agent-memory note show    -i <id>
agent-memory note edit    -i <id>                   # opens $EDITOR

# Search
agent-memory search       -q <query> [-p <project>] [-k <kind>]

# Index management
agent-memory index rebuild [-r <root>]
agent-memory index status  [-r <root>]
```

---

## `llm_local` Module Design

**Location:** `scripts/modules/llm_local/`  
**Size:** ~80 lines, zero non-stdlib deps  
**Import:** `from llm_local import complete`

```python
def complete(
    prompt: str,
    *,
    model: str | None = None,
    url: str | None = None,       # default: LM_STUDIO_URL env or http://localhost:1234/v1
    timeout: float = 5.0,
    system: str | None = None,
) -> str | None:
    """Call local LM Studio inference. Returns None if unreachable (never raises)."""
```

Uses `urllib.request` only. Parses OpenAI-compatible `/chat/completions` response.
Catches all network errors and returns `None` — callers always handle the None case.

---

## Integration Points

### `agent_sync` → `agent_memory`

`agent-sync memory sync -t <task-id>` (Phase 3 of agent_sync):
1. Read run events from agent_sync SQLite
2. Call `store.create_note(kind="handoff", project=<repo-slug>, ...)`
3. Write session summary note

### `ai-orchestrator` → `agent_memory`

`memory/ingest_notes.py` (planned in ai-orchestrator):
1. Call `store.list_notes()` to get all notes
2. Check `content_hash` against pgvector records to detect changes
3. Push changed notes into pgvector via existing `source_ingestion.py`

---

## Out of Scope (V1)

- pgvector push command
- Memory compaction / LLM-assisted merge
- `promote` command (project → global)
- `status`, `confidence`, `related`, `supersedes` frontmatter fields
- Generated `_index.md` rollups
- MCP adapter
- Retention / eviction policy
