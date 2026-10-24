# Phase 6C: Existing Capabilities & Architecture Matrix

**Date:** 2026-10-24
**Workstream:** Runmux Phase 6C (Historical Run Discovery & Events Backend)
**Baseline Commit:** `8befeae3375740e21cdfe17a081387f0e3cf8f54` (Phase 5C integrated into `main`)

---

## 1. Three Core Data Categories

Before implementing historical run discovery and events, Runmux explicitly distinguishes three fundamentally different categories of historical data:

| Category | Definition | Source of Truth | Storage Engine | Retention & Lifecycle | Primary Identification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Run History** | Persistent records of processes ever managed (pending, running, finished, failed, killed, lost). | `registry.sqlite3` (`runs` table) | SQLite (WAL mode) | Permanent until explicitly pruned (`prune_terminal_runs`, `clean`) | Immutable Run ID (`YYYYMMDD-HHMMSS-xxxxxx`) & recycled `numeric_id` |
| **2. Metric History** | Periodic time-series resource measurements (CPU, RSS, I/O, threads, GPU) sampled while `runmux web` is running. | `telemetry.sqlite3` (`telemetry_*` tables) | SQLite (WAL mode, incremental auto-vacuum) | Multi-tier: 1h raw, 24h 1-minute rollup, 7d 5-minute rollup (50 MB target budget) | Partitioned by `(run_id, timestamp)` |
| **3. Lifecycle Events** | Discrete state transitions and supervisor operations with verified event provenance. | `telemetry.sqlite3` (`telemetry_events` table) & `runs` timestamp deltas | SQLite (`telemetry_events`) & structured registry attributes | 7-day retention in telemetry store; permanent state markers in registry | `(run_id, timestamp, event_type)` |

> [!IMPORTANT]
> **Metric samples do not establish authoritative lifecycle events.** While gaps in periodic metric samples indicate process pauses or supervisor restarts, authoritative lifecycle events must have genuine provenance (supervisor operation records or verified state transitions). Inferred state changes must never masquerade as recorded events.

---

## 2. Existing Capabilities Matrix

| Functional Area | Current Capability in Codebase | Limitations & Gaps | Target in Phase 6C |
| :--- | :--- | :--- | :--- |
| **Run Record Storage** | Stores 24 structured attributes in `registry.sqlite3` (`runs` table) including `created_at`, `started_at`, `ended_at`, `exit_code`, `pid`, `restart_of`, `duplicate_of`. | No secondary indexes on `status`, `created_at`, `ended_at`, `name`, `restart_of`, or `duplicate_of`. Queries scan table sequentially. | Add targeted indexes via `migrate_db` to support $O(\log N)$ historical queries. |
| **Process Listing (`GET /api/runs`)** | Returns an unbounded array of all runs in registry ordered by active status then `created_at DESC`. | Non-deterministic ordering when `created_at` collisions occur (no tie-breaker). Memory consumption scales linearly with registry size. | Preserve existing contract for `GET /api/runs` (unbounded array), add optional pagination params, and introduce `GET /api/runs/history`. |
| **Pagination** | None. `RunStore.list_runs` accepts only an integer `limit`. | Offset pagination (`LIMIT/OFFSET`) causes row skipping/duplication when runs are added or state changes. Unbounded scans. | Implement deterministic keyset (cursor) pagination using `(sort_value, id)` with base64url opaque cursors. |
| **Filtering** | `RunStore.list_runs` supports only `statuses: list[str]`. | No filtering by time range (`since`/`until`), name, exit code, recent failures, lost runs, or restart/duplicate relationships. | Support multi-attribute filtering: `status`, `state` (active/terminal), `since`/`until`, `name`, `exit_code`, `failed_only`, `lost_only`, `restart_of`. |
| **Sorting** | Hardcoded: `CASE WHEN status IN ('pending', 'running', 'paused') THEN 0 ELSE 1 END, created_at DESC`. | Cannot sort by `started_at`, `ended_at`, `name`, or `numeric_id`. Inconsistent ordering on timestamp collisions. | Support sorting by `created_at`, `started_at`, `ended_at`, `name`, `numeric_id` with `id` tie-breaker. |
| **Lifecycle Events** | `telemetry_store.py` provides `telemetry_events` table (`event_id`, `run_id`, `timestamp`, `event_type`, `reason`, `details_json`). | Only queried within `/api/runs/{id}/telemetry/history` window. No standalone endpoint for process lifecycle events. | Provide dedicated `GET /api/runs/{id}/events` combining recorded telemetry events and structured registry transitions with explicit provenance. |
| **Lineage & Relationships** | `runs` table records `restart_of` and `duplicate_of` Run IDs. `web_adapter.py` walks `restart_of` backward for telemetry charts. | Forward traversal (who restarted this run?) requires full scan. No dedicated relationship API. | Provide relationship mapping and forward/backward lineage resolution with cycle detection. |
| **Security & Privacy** | `serialize_run` allowlists safe fields, redacting `argv_json`, `cwd`, `env_overrides_json`, `auth_token`, `port`. | Must guarantee new history search and discovery endpoints do not leak redacted environment variables, arguments, or tokens. | Re-use strict allowlist serialization across all new historical query and event responses. |

## 3. Phase 6C Implementation Outcome

- `GET /api/runs` remains the existing array response. New historical browsing is isolated in `GET /api/runs/history` and uses SQL filters, keyset cursors, deterministic Run ID tie-breaking, a first-page creation watermark, a 1–200 item limit, and a SQLite VM-step budget.
- Queryable sort keys are `created_at`, `started_at`, `ended_at`, `name`, and `numeric_id`. Time bounds are inclusive and normalized to UTC second precision. Exact counts are opt-in because they may scan every matching row.
- A page reads current registry state when requested. The cursor avoids offset shifting and excludes runs with a later creation timestamp; a same-second new run with a lower Run ID may still appear. Status updates can change membership between pages. This is not a cross-request database snapshot.
- `GET /api/runs/{run_id}/events` returns chronological cursor pages of at most 1,000 entries. Recorded telemetry rows are labeled `telemetry_store`; timestamp markers and stored restart/duplicate links are labeled `registry_record`. No transition is inferred from metric samples. Free-text reason and arbitrary event details are withheld.
- `GET /api/runs/{run_id}/lineage` traverses explicit restart and duplicate Run IDs in both directions. The response caps each path at the requested limit, sets `truncated`, and reports direct relationship counts for the requested run.
- New adapters use read-only SQLite connections. History items and lineage nodes use allowlists. The API routes are attached to the existing authenticated `/api` router.
- The 10,000-record disposable registry benchmark is in `tests/historical_runs_api_test.py`; latest recorded timings are in the Phase 6C status report.
