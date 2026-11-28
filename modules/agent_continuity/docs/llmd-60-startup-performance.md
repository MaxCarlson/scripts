# LLMD-60 Startup Profiling, Registry Sync Optimization & Native Bootstrap Contract

## Hardware & Runtime Provenance

- **OS / CPU**: `Windows-11-10.0.26300-SP0 AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD` (32 logical CPUs)
- **Python**: `3.12.10`
- **Installed Provider CLIs**: `codex-cli 0.172.0`, `agy 1.5.18`
- **Read-Only Production Registry**: `C:\Users\mcarls\.agent_continuity` (426 spool events in `events/`, `index.sqlite`)

## 1. Empirical Pre-Bootstrap Cost Breakdown

Measured via read-only inspection and a disposable copy of `C:\Users\mcarls\.agent_continuity`:

| Phase | Cold | Warm | Notes |
| --- | --- | --- | --- |
| `import agent_continuity.dispatcher_cli` | `89.62 ms` | — | CLI module + parser import |
| `PsutilProcessEnumerator().enumerate_processes()` | `6982.59–7201.77 ms` | `153.87 ms` | Windows ~712 processes; first cold scan dominates |
| `read_spool_events` (426 events, baseline) | `84.66 ms` | `68.98–74.91 ms` | Full `rglob` + open/read/JSON-parse/SHA-256 of every file |
| `sync_from_spools` (426 events, baseline) | `1335.47 ms` | `89.52 ms` | Called 3x across `_start` -> `prepare_start` -> `_run_pane_locked` |
| `atomic_write_json` (`nt.fsync`) | `~106–137 ms / event` | — | Per-event durable `os.fsync` |
| Provider `READY` bootstrap (`codex exec` / `agy --print`) | `12–40+ s` | `12–40+ s` | Full LLM inference round-trip before launching interactive `resume` |

## 2. Implemented Spool Synchronization Optimization (`events.py`, `materializer.py`)

- Added `os.scandir`-based `_scan_spool_entries` and `read_spool_events_incremental` in [events.py](../agent_continuity/events.py).
- Persisted `spool_file_fingerprints_v1` (`path -> [size, mtime_ns]`) inside `schema_metadata` in the same SQLite transaction as `ingest_events`, `sync_from_spools`, and `rebuild_from_spools` in [materializer.py](../agent_continuity/materializer.py).
- When `index.sqlite` matches `SCHEMA_VERSION` and every on-disk spool file's `(size, mtime_ns)` matches `spool_file_fingerprints_v1`, `sync_from_spools()` returns from the read-only fast path without opening, parsing, or hashing any spool JSON files or opening a read-write SQLite connection.
- Concurrent appends (new paths), rotated duplicates (new paths with existing `event_id`), truncated files (`size` change), and replaced files (`size`/`mtime_ns` change) are all detected and processed through `_apply_event_in_tx` and `SpoolIssue` reporting.

### Before / After Benchmark Results

| Registry Size | Full Scan Median (Baseline) | Warm Incremental Median (After) | Speedup | Append-1 Incremental |
| --- | --- | --- | --- | --- |
| Prod copy (426 events) | `89.52 ms` (`sync_from_spools`) | `6.29 ms` (`min=5.13`, `max=9.99`) | **14.2x** | — |
| Synthetic 500 events | `82.07 ms` | `7.80 ms` | **10.5x** | `272.14 ms` (includes RW commit) |
| Synthetic 1000 events | `134.81 ms` | `13.22 ms` | **10.2x** | `253.69 ms` (includes RW commit) |
| Synthetic 2500 events | `379.50 ms` | `27.71 ms` | **13.7x** | `599.06 ms` (includes RW commit) |

## 3. Dispatcher Call-Site Coordination Notes (Agent #1 Owned)

1. **Deduplicate `_sync()` calls on `llmd start` / `llmd new`**: `_start` currently syncs before preview, `prepare_start` syncs again under `_mutation_lock`, and `_run_pane_locked` syncs a third time. Passing a `synced=True` hint or skipping redundant `_sync()` when `_emit_and_materialize` just updated SQLite removes repeated sync overhead.
2. **Avoid cold `PsutilProcessEnumerator` when no session is selected**: New-session creation (`_start` with no existing selected session) does not need a full 712-process Windows inventory (~7s cold). Scope process enumeration to commands that inspect an existing selected session (`observe_runtime_session`).

## 4. Native Bootstrap Elimination Contract (Agent #1 Integration)

Current LLMD executes a fixed `READY` model request (`codex exec --json --sandbox read-only ...` / `agy --print ... --output-format json --sandbox`), incurring 12–40+ seconds of LLM latency before launching interactive resume.

| Provider | Verified Installed Mechanism | Deterministic Session ID Capture | Interactive Launch |
| --- | --- | --- | --- |
| **Claude** | `claude --session-id <UUID>` | Pre-generated UUIDv4 passed directly (already implemented) | `claude --session-id <UUID>` |
| **Codex (`0.172.0`)** | `codex app-server --stdio` (`thread/start` JSON-RPC request) | Server returns exact `thread.id` without running a model turn; verified in `~/.codex/state_5.sqlite` (`threads`) & `session_meta` | `codex resume <thread_id>` |
| **AGY (`1.5.18`)** | `agy acp --stdio` (ACP `initialize` + `session/new` JSON-RPC) | Server returns exact `sessionId` without running a model turn | `agy --conversation <sessionId>` |

- **Fail-closed invariant**: Never fall back to `--last`, `--continue`, or recency-ordered directory scans. If `app-server` / `acp` session creation fails or returns ambiguous/missing IDs, abort launch reservation without guessing.
