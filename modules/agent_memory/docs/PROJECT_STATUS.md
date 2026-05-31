# Agent Memory — Project Status

> **For incoming LLMs:** Read this file first. It tells you exactly where the
> project stands, what's been decided, what's been built, and what to do next.
> All design decisions are in `docs/design/agent-memory-design.md`.
> All implementation plans are in `docs/plans/`.

---

## Current State: 2026-05-31

### Phase 0 — Decision & Design ✅ COMPLETE

Design brainstormed and approved. See `docs/design/agent-memory-design.md` for
the full spec.

Two modules being created in this work session:
- `scripts/modules/llm_local/` — thin local LLM inference client (~80 lines)
- `scripts/modules/agent_memory/` — notes storage, SQLite index, CLI, LLM classification

### Phase 1 — `llm_local` module ✅ COMPLETE

**Plan:** `docs/plans/PLAN-1-LLM-LOCAL.md`

Dependency: none. Must be built before `agent_memory` (which imports it).

### Phase 2 — `agent_memory` core ⏳ NOT STARTED

**Plan:** `docs/plans/PLAN-2-CORE.md`

NoteStore class, file I/O, frontmatter parsing, SQLite index, rebuild command.

### Phase 3 — `agent_memory` CLI ⏳ NOT STARTED

**Plan:** `docs/plans/PLAN-3-CLI.md`

`agent-memory note create/list/show/edit`, `search`, `index rebuild/status`.

### Phase 4 — `agent_sync` integration ⏳ NOT STARTED

**Plan:** `docs/plans/PLAN-4-INTEGRATION.md`

Wire `agent-sync memory sync` command (Phase 3 of agent_sync) to use
`agent_memory.NoteStore`. Also wire `llm_local` into `agent_memory` for
placement classification.

---

## Related Modules (context for incoming LLMs)

### `scripts/modules/agent_sync/` — Multi-agent coordination ⏳ PHASE 2 IN PROGRESS

Phase 1 (Foundation) complete: DB schema, state layer (tasks/runs/claims/
handoffs/events), hook dispatcher, worktree manager, docs renderer,
`agent-sync init` + `doctor` CLI, `AgentAdapter` ABC + `ClaudeAdapter`.

Phase 2 (Sequential Handoff) — **paused** to build `agent_memory` first.
Plans at: `agent_sync/agent_sync/docs/plans/PLAN-2-SEQUENTIAL.md`

Resume Phase 2 after `agent_memory` Phases 1–3 are complete.

### `projects/ai-orchestrator/memory/` — Heavy memory stack (PostgreSQL + pgvector)

Separate project. `agent_memory` provides its Tier 1 notes layer.
Integration: `memory/ingest_notes.py` (planned) will call `agent_memory.NoteStore`
to push notes into pgvector.

---

## Key Design Decisions Made

| Decision | Rationale |
|---|---|
| One Markdown file per note (Option A) | Atomic writes, no merge conflicts, agent-safe |
| SQLite as rebuildable index (not source of truth) | Fast filters, zero infra, FTS5 support |
| Path = primary kind truth; frontmatter `kind` = validation | Avoids dual-source ambiguity |
| `llm_local` as separate module | Reusable by agent_sync, ai-orchestrator, others |
| Decision logic (placement prompts) stays in agent_memory | Keeps llm_local infrastructure-only |
| Deferred: pgvector, compaction/merging, auto-summarization | Phase 2+ |
| Deferred: status/confidence/related/supersedes frontmatter fields | V2 |
| `AGENT_MEMORY_ROOT` env var + `--root` flag | Configurable, defaults to module notes/ dir |

---

## How To Resume This Project

1. Read this file
2. Read `docs/design/agent-memory-design.md` (full spec)
3. Check which phases are ✅ vs ⏳ above
4. Read the plan doc for the next incomplete phase
5. Run existing tests: `cd scripts/modules/agent_memory && uv run pytest tests/ -v`
6. Continue from where the plan left off
