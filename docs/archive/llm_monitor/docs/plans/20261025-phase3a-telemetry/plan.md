# LLM Monitor Phase 3A Implementation Plan

> **For agentic workers:** Execute this plan inline, task by task. Do not delegate.

**Goal:** Persist privacy-safe observations from multiple OpenCode sessions and provide offline history and reports.

**Architecture:** Preserve the Phase 2 collector, normalized events, and diagnostic rules. Add a standard-library SQLite store, a recording coordinator that ingests existing poll/history results, read-only query APIs, and CLI commands for recording, history, database checks, pruning, and persisted reports.

**Tech Stack:** Python 3.11+, `argparse`, `sqlite3`, JSON, pytest.

**Spec:** Phase 3A handoff supplied in the task; Phase 2 behavior is documented in `README.md` and `docs/plans/20261025-llm-monitor-phase2/`.

## Global Constraints

- Do not modify OpenCode, LM Studio, MCP, model configuration, local_agent_bridge, resource coordinator, original forensic evidence, or other worktrees.
- Store no prompts, completions, tool output, raw provider responses, environment values, or arbitrary tool arguments.
- Keep cumulative token totals separate from per-inference context usage.
- Use SQLite WAL, parameterized SQL, explicit transactions, `user_version` migrations, and idempotent event identities.
- A missing/partial source remains explicit; do not fabricate recovered history.
- Destructive pruning previews by default and requires `-w/--write`.
- Preserve existing commands and JSON fields; report historical data only when explicitly requested.

## Decisions

- Database defaults to LocalAppData on Windows, Application Support on macOS, and XDG data home (or `~/.local/share`) on Linux/WSL2/Termux.
- No automatic retention or size cap is applied. Manual age pruning is available with a dry-run preview; the database has no configured size limit and reports its measured size.
- SQLite coordinates multiple writers with WAL, `busy_timeout`, `BEGIN IMMEDIATE`, and unique event constraints rather than a process lock file.
- File targets are stored as SHA-256 identifiers to retain repeated-path analysis without persisting raw paths. Display metadata omits session titles and working directories by default.
- Existing `-d/--directory` remains unchanged on current commands. New commands use `-d/--database`; `report` uses `-D/--database` because `-d` already means project directory there.
- A new recording session fetches the provider's currently retrievable history once; subsequent intervals use existing bounded polling. Restarts replay a recent overlap and deduplicate; full legacy windows create explicit partial-coverage gaps.

## Stage A — Verify and stabilize Phase 2

- [x] Confirm feature branch remote head and clean status.
- [x] Run the Phase 2 suite and compile checks.
- [x] Probe already-running OpenCode and LM Studio endpoints without starting services.
- [x] Probe `resource_metrics` once; retain point-in-time/device attribution limits.
- [x] Verify installed CLI from an isolated package installation.
- [x] Review event collection, privacy projection, CLI, and existing JSON schemas.

## Stage B — Storage foundation

- [x] Test default paths, fresh initialization, schema version, future/incomplete-schema rejection, read-only open, and integrity handling.
- [x] Implement versioned schema for provider instances, sessions, jobs, events, inference/compaction/tool details, hardware samples, checkpoints, and gaps.
- [x] Test privacy projection, stable provider-scoped identity, idempotent ingest, transaction rollback, and two writers.
- [x] Add indexed paginated queries and database info/check/prune APIs.

## Stage C — Recording and recovery

- [x] Test initial collection, repeated polls, checkpoints, cursor/legacy coverage, failures, and multiple sessions.
- [x] Implement a recorder over `OpenCodeClient` with initial history sync, bounded live polling, one transaction per poll, and clean Ctrl+C.
- [x] Add explicit persisted state observations and coverage gaps without changing live `watch` behavior.
- [x] Test restart replay, batch rollback, competing writers, and provider/session isolation.

## Stage D — Historical analysis

- [x] Test offline historical analysis over persisted events and coverage.
- [x] Implement `history` APIs and session listings without requiring providers online.
- [x] Add `report --history` using existing analysis/diagnostic functions and stored model/capacity metadata when supported.
- [x] Add restart/interruption fixtures and a 10,000-event ingestion/query workload.

## Stage E — CLI, operations, documentation

- [x] Add `record`, `history`, and `db info|check|prune` commands and database path options.
- [x] Preserve Phase 2 parser and JSON contract tests.
- [x] Document paths, privacy, retention, recovery, multi-writer behavior, and Windows/POSIX examples.
- [ ] Run the full module suite, isolated install/entry-point check, compile/help checks, and final repository review.

## Review Focus

- Duplicate collectors racing on the same event must not duplicate facts or advance checkpoints inconsistently.
- Corrupt and future-version database files must remain untouched and report a clear error.
- SQLite WAL checkpoint files and database parent directories must remain beside the selected local database, never OpenCode's data directory.
- Missing timestamps and no-ID events must use deterministic fallback keys without claiming collision-free identity.
- File paths, session titles, tool arguments, and outputs must not leak through event payloads, reports, or error messages.
- Pruning must not delete by default and must preserve session/coverage explanations for removed intervals.
