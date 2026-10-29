# LLM Monitor Phase 3C Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current session. Each task adds tests before implementation.

**Goal:** Provide one shared observability API for a native multi-session TUI and evidence-based alert state, with a Runmux integration contract that does not conflict with active Runmux work.

**Architecture:** `ObservabilityService` owns a single OpenCode polling coordinator and optionally reads persisted sessions through `TelemetryStore`. Stable versioned summary/detail models feed both TUI rendering and alert evaluation. Alert rules consume existing findings and current observations; a compatible SQLite migration persists deduplicated alert transitions. A standard-library terminal loop avoids hard TUI dependencies. Direct Runmux edits are deferred because Runmux web/UI implementation is active in other worktrees; publish an authenticated read-only API contract instead.

**Tech Stack:** Python 3.11+, argparse, SQLite, standard-library terminal input/rendering; optional existing termdash table renderer.

**Spec:** User-provided “LLM Monitor — Phase 3C Implementation Handoff” (2026-10-28).

## Global Constraints

- Preserve existing Phase 1–3B CLI contracts and telemetry meanings.
- Do not touch `modules/local_agent_bridge/`, OpenCode databases, live processes, or Runmux process state.
- Do not initiate inference, change models, or send external notifications.
- Keep telemetry collection opt-in; dashboard polling alone is live-only.
- Preserve unknown, stale, historical, and provider-observed state distinctions.
- Support Python 3.11+ and graceful operation when optional GPU/TUI packages are unavailable.

## Review Focus

1. **Provider disconnect after active generation:** surface stale/unknown freshness; do not keep a confident running state.
2. **No database or schema-v1 database:** live-only dashboard remains usable; optional historical panel is unavailable gracefully.
3. **Concurrent dashboard/recorder/database users:** alert state writes are transactional and do not alter event checkpoints.
4. **Terminal width, cancellation, and malformed key input:** bounded layout and restored terminal mode.
5. **Repeated evaluation/restart:** deduplicate persisted alert conditions and retain acknowledgment without replay floods.

---

### Task 1: Shared application-facing observability API

**Files:** create `llm_monitor/observability.py`, `tests/observability_test.py`.

**Interfaces:** `ObservabilityService.refresh() -> SystemSnapshot`; `get_detail(provider_instance_id, session_id) -> SessionDetail | None`; immutable versioned models for system, summary, detail, freshness, and timeline; no writes unless explicitly provided a recording service (not planned for TUI).

- [x] Test live session aggregation, persisted history inclusion, state freshness, offline behavior, provider disconnects, and one refresh cycle.
- [x] Implement service using one `OpenCodeClient`, existing normalized events/analysis, and optional read-only `TelemetryStore`.
- [x] Verify focused tests and legacy watch tests.

### Task 2: Durable alert engine and compatible storage migration

**Files:** create `llm_monitor/alerts.py`, `tests/alerts_test.py`; modify `storage.py`, `tests/storage_test.py`, `cli.py`, `tests/cli_test.py`.

**Interfaces:** `evaluate_alerts(snapshot, rules=DEFAULT_RULES, previous=...) -> list[AlertTransition]`; rules have stable IDs, thresholds, evidence minima, windows, cooldown/hysteresis; store APIs list/upsert/ack alert state.

- [x] Test supported findings, blockers, stale provider, no-evidence behavior, and analyzer code compatibility; hardware/database alerts remain unsupported without sustained source samples.
- [x] Test transition dedupe, resolution, acknowledgment, stale evidence retention, and schema-v1 migration.
- [x] Migrate database v1 to v2 transactionally, adding only alert-state tables; continue read-only v1 opening for telemetry queries.
- [x] Add `alerts list|rules|test|acknowledge`; test evaluation is read-only.
- [x] Verify focused tests and existing module suite.

### Task 3: Native interactive TUI

**Files:** create `llm_monitor/tui.py`, `tests/tui_test.py`; modify `cli.py`, `tests/cli_test.py`.

**Interfaces:** pure `render_overview`, `render_detail`, `TuiState.handle_key`; terminal adapter controls input and cleanup; `llm-monitor tui [-s SESSION] [-a] [-d DB] [-i SECONDS] [-v]`.

- [x] Test session selection, detail/overview navigation, search, sort, pause, refresh, narrow layout, stale/offline labels, unknown metrics, and render clipping with deterministic input.
- [x] Implement console capability checks, Windows `msvcrt` and POSIX cbreak input, terminal restoration, resize-aware bounded rendering, and graceful exit.
- [x] Use termdash's table component only when importable; basic text layout remains dependency-free.
- [x] Verify CLI help and existing `watch` compatibility.

### Task 4: Runmux integration contract

**Files:** create `docs/API.md`; modify `README.md`.

- [x] Document JSON schema version 1, read-only operations, bounds/pagination, provider/session IDs, freshness and coverage semantics, authentication boundary, and no process lifecycle operations.
- [x] Record that direct Runmux adapter/UI integration is deferred to the active Runmux owner.
- [x] Confirm no Runmux-owned path is changed.

### Task 5: Integration and delivery

- [x] Run all LLM Monitor tests, Scripts Help tests, `compileall`, CLI help, and diff checks.
- [x] Exercise deterministic synthetic multi-session load and report wall time and traced peak memory.
- [x] Build/install package in an isolated virtual environment; inspect changed paths and protected scope.
- [ ] Commit, push, and verify remote SHA.
