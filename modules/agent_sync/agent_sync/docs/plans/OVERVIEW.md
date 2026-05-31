# Agent Sync — Module Overview & Phased Roadmap

> **For agentic workers:** Read this document first to understand scope and
> dependencies between sub-plans. Then read the specific sub-plan for the phase
> you are implementing. Each sub-plan is self-contained and produces working,
> testable software independently.

**Goal:** Build `agent_sync`, a repo-local Python module that gives deterministic
multi-agent coordination for sequential handoffs between Claude Code, Codex, and
Gemini CLI, and for parallel child-task delegation to any agent including local
GPU workers.

**Core insight:** The repository itself is the coordination substrate. Any agent
that can read a git repo and a SQLite file can resume any task from any other
agent. Provider-native sessions, memories, and transcripts are optional
accelerators, never required.

---

## What This Is Not

- Not a replacement for the existing orchestrator (`docker/orchestrator/main.py`).
  The orchestrator dispatches tasks from `task_queue/` to CLI workers. `agent_sync`
  operates at a higher level: it manages which agent picks up a task, tracks
  ownership, and coordinates handoffs and merges. For local worker delegation,
  `agent_sync` reuses the existing `task_queue/` infrastructure.

- Not a new memory system. The existing `memory/` module with pgvector handles
  RAG. `agent_sync` maintains its own lightweight SQLite for runtime coordination
  state (runs, claims, handoffs) and writes human-readable Markdown summaries to
  `agent_sync/docs/`. Integration with `memory/` for cross-session knowledge is
  optional and deferred to Phase 3.

- Not Obsidian. The `agent_sync/docs/` folder is plain Markdown the operator can
  open in any editor.

---

## Two Operating Modes

### Mode 1 — Sequential Handoff

You are working with Claude Code on a feature. You want to hand off to Codex or
Gemini without losing context. `agent_sync` writes a deterministic `HANDOFF.md`
when Claude stops, and injects a `SESSION_BRIEF.md` when the next agent starts.
The receiving agent reads the repo state + these two documents and continues
exactly where the previous agent left off.

```
claude → agent-sync handoff → codex → agent-sync handoff → gemini → ...
```

Key properties:
- Works across vendors and machines.
- Surviving state is Markdown + SQLite — no vendor session IDs required.
- Vendor-native session resume (e.g. `claude --resume`) works on top of this as
  an optional acceleration when the same vendor is reused.

### Mode 2 — Parallel Delegation

A primary agent (usually Claude or Codex) identifies bounded subtasks and
delegates them. Each child task runs in an isolated Git worktree with file-level
claim locks so edits cannot collide. An integration gate merges completed child
branches with a `--no-ff` merge commit after running acceptance commands.

```
claude (primary, worktree 1)
  ├─► codex delegate (worktree 2) — bounded refactor
  ├─► local worker (task_queue) — test generation
  └─► gemini review (worktree 3, read-only) — code review
         → agent-sync integrate → main
```

Key properties:
- One primary writer per path at a time (SQLite claim locks).
- Child tasks get their own branches and worktrees, merged only through the
  integration gate.
- Local workers reuse the existing `task_queue/` + `cli_integrations/local_worker.sh`
  infrastructure.

---

## Repository Layout (Final State)

```
agent_sync/                        ← Python module
  __init__.py
  cli.py                           ← argparse CLI, entry point: agent-sync
  db/
    __init__.py
    connection.py                  ← SQLite WAL/FK/timeout helper
    schema.py                      ← DDL constants + initialize_schema()
  state/
    __init__.py
    tasks.py                       ← Task dataclass + CRUD
    runs.py                        ← Run dataclass + CRUD + heartbeat
    claims.py                      ← file-level lease management
    handoffs.py                    ← Handoff dataclass + CRUD
    events.py                      ← append-only event/artifact log
  adapters/
    __init__.py
    base.py                        ← AgentAdapter ABC
    claude.py                      ← ClaudeAdapter
    codex.py                       ← CodexAdapter
    gemini.py                      ← GeminiAdapter
    local.py                       ← LocalWorkerAdapter (wraps task_queue/)
  hooks/
    __init__.py
    dispatch.py                    ← python -m agent_sync.hooks.dispatch
    normalize.py                   ← provider payload → HookEvent dataclass
    handlers/
      __init__.py
      session_start.py
      pre_tool.py
      post_tool.py
      stop.py
  shell/
    claude-dispatch.sh             ← thin wrapper → dispatch.py
    codex-dispatch.sh
    gemini-dispatch.sh
  worktree.py                      ← git worktree lifecycle
  routing.py                       ← task scoring + agent selection
  docs_gen/
    __init__.py
    templates.py                   ← string templates for Markdown docs
    renderer.py                    ← render_session_brief(), render_handoff()
  commands/
    __init__.py
    init.py                        ← agent-sync init
    start.py                       ← agent-sync start
    handoff_cmd.py                 ← agent-sync handoff
    resume.py                      ← agent-sync resume
    dispatch_cmd.py                ← agent-sync dispatch (parallel)
    review.py                      ← agent-sync review
    integrate.py                   ← agent-sync integrate
    doctor.py                      ← agent-sync doctor
    memory_sync.py                 ← agent-sync memory sync
  docs/                            ← runtime-generated Markdown (gitignored content)
    plans/                         ← implementation plans (this folder)
    AGENT_CONTRACT.md              ← static, written by agent-sync init
    SESSION_BRIEF.md               ← updated on every session start
    HANDOFF.md                     ← updated on every stop/handoff
    TASKS/                         ← per-task human-readable ledgers
  manifests/                       ← per-task YAML routing contracts
  runs/                            ← per-run append-only artifact trees
  db/
    state.sqlite3                  ← runtime source of truth

# Provider config (written/updated by agent-sync init):
AGENTS.md                          ← Codex instruction entrypoint
CLAUDE.md                          ← Claude instruction entrypoint (project root)
GEMINI.md                          ← Gemini instruction entrypoint
.claude/settings.json              ← hook registration for Claude Code
.codex/config.toml                 ← profiles + MCP for Codex
.codex/hooks.json                  ← hook registration for Codex
.codex/rules/agent_sync.rules      ← guarded command policy for Codex
.gemini/settings.json              ← hook registration for Gemini CLI

# Worktrees (gitignored):
.agent_sync/worktrees/             ← module-managed worktree roots

# Tests:
tests/
  test_agent_sync_db_test.py
  test_agent_sync_state_test.py
  test_agent_sync_claims_test.py
  test_agent_sync_worktree_test.py
  test_agent_sync_hooks_test.py
  test_agent_sync_routing_test.py
  test_agent_sync_integration_test.py
```

---

## CLI Commands

All flags have both short and long forms. Every subcommand supports `-h/--help`.

| Command | Purpose |
|---|---|
| `agent-sync init` | Bootstrap DB, provider configs, shell wrappers, AGENT_CONTRACT.md |
| `agent-sync start -t <id> -a <agent>` | Start or attach a task to an agent + worktree |
| `agent-sync handoff -t <id> -a <to-agent>` | Freeze run, write HANDOFF.md, prepare next agent |
| `agent-sync resume -t <id>` | Reconstruct state and relaunch the assigned agent |
| `agent-sync dispatch -m <manifest>` | Fan out child tasks from a manifest |
| `agent-sync review -t <id> -a <agent>` | Launch reviewer agent against task branch |
| `agent-sync integrate -t <id>` | Rebase + guarded merge to target branch |
| `agent-sync doctor` | Verify hooks, trust, worktrees, DB |
| `agent-sync memory sync -t <id>` | Distill run state into memory/notes/ |

---

## Sub-Plans

The implementation is split into three independent, sequentially-dependent phases.
Each phase produces working, testable software.

| Sub-Plan | File | Produces |
|---|---|---|
| Phase 1 — Foundation | `plans/PLAN-1-FOUNDATION.md` | DB, state layer, worktrees, docs renderer, CLI skeleton, hook dispatcher |
| Phase 2 — Sequential Handoff | `plans/PLAN-2-SEQUENTIAL.md` | All three adapters (Claude, Codex, Gemini), full start→handoff→resume flow |
| Phase 3 — Parallel Delegation | `plans/PLAN-3-PARALLEL.md` | Routing, dispatch, integration gate, local worker delegate path |

**Dependencies:**
- Phase 2 requires Phase 1 complete.
- Phase 3 requires Phase 2 complete.
- Each phase can be implemented by a separate agent session using Phase 1's
  `SESSION_BRIEF.md` / `HANDOFF.md` as continuity artifacts.

---

## Provider Hook Notes

### Claude Code
- Hook config: `.claude/settings.json` under `hooks` key.
- Events: `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`.
- Shell path variable: `${CLAUDE_PROJECT_DIR}` resolves reliably.
- Non-interactive: `claude -p "<prompt>" --bare`.
- Session resume: `claude --resume <session-id>` (same-machine only, optional).

### Codex
- Hook config: `.codex/hooks.json`.
- Events: same four as Claude, same JSON-on-stdin protocol.
- Shell path: resolve via `git rev-parse --show-toplevel` (Codex may start in a subdirectory).
- Non-interactive: `codex exec`.
- **Caveat:** Codex project hooks require explicit trust. `agent-sync doctor` verifies this.
- **Caveat:** `PreToolUse` interception is incomplete for Codex shell paths. Enforce via claim locks, not hooks alone.

### Gemini CLI
- Hook config: `.gemini/settings.json` under `hooks` key (same schema as Claude).
- Instruction file: `GEMINI.md` (same role as CLAUDE.md/AGENTS.md).
- Events: `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`.
- Shell path: resolve via `git rev-parse --show-toplevel` (same as Codex).
- Non-interactive: `gemini -p "<prompt>"` or `gemini --prompt-file <file>`.
- **Note:** Verify exact hook key names against the installed version's docs/`gemini --help`.
  The schema above matches the documented pattern as of 2026-05; if keys differ,
  `agent_sync/adapters/gemini.py` is the only file that needs updating.

---

## Security Layering

Security is layered, not delegated to any single mechanism:

1. **Worktree isolation** — parallel agents physically cannot touch each other's files.
2. **SQLite write claims** — claim check blocks even same-worktree path collisions.
3. **Provider permissions** — Claude `permissions.deny`, Codex sandbox + rules.
4. **Hook guards** — `PreToolUse` blocks specific dangerous commands as second line.
5. **Integration gate** — no merge without explicit validation pass.

Guarded commands (blocked by policy in `PreToolUse` + provider rules):
`git push`, `git commit` outside integrate, `gh pr create/merge`, DB migrations to
non-local hosts, `rm -rf`, `sudo`, package publish, writes to `.env`/credentials.

---

## Integration with Existing Repo Infrastructure

| Existing component | Role in agent_sync |
|---|---|
| `task_queue/` + `shared/task_queue.py` | Local worker delegate path: `agent-sync dispatch` with `agent=local` creates tasks here; `bin/local_worker_loop.sh` picks them up |
| `memory/` (pgvector, hybrid search) | Optional: `agent-sync memory sync` distills HANDOFF.md + events into `memory/notes/` via the planned `memory/ingest_notes.py` CLI |
| `docker/orchestrator/main.py` | Unchanged. agent_sync is a higher-level coordination layer above it |
| `chat/src/` (`aioc`) | Unchanged. agent_sync manages multi-agent runs; aioc is a single-agent chat interface |
| `.claude/settings.json` | agent-sync init writes hook entries here (merging with any existing content) |

---

## Guiding Principles

- **One primary writer per path per task.** Parallelism via child tasks + isolated worktrees only.
- **Repo state wins.** If vendor session memory and repo state disagree, repo state is truth.
- **Review queue.** Generated handoff candidates are Markdown files. Integration to `main` requires an explicit `agent-sync integrate` call with passing acceptance commands.
- **Offline capable.** `agent-sync start`, `handoff`, `resume` work without network. Memory sync is opt-in.
- **No silent writes.** Any command that writes to the DB or creates/modifies files in the repo says so explicitly with `--dry-run / -n` support.
