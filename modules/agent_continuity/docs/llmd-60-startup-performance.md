# LLMD-60 Startup Profiling, Registry Sync Optimization & Native Bootstrap Contract

## Hardware & Runtime Provenance

- **OS / CPU**: `Windows-11-10.0.26300-SP0 AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD` (32 logical CPUs)
- **Python**: `3.12.10`
- **Installed Provider CLIs**: `codex-cli 0.172.0`, `agy 1.5.18`, `claude 2.1.332`
- **Read-Only Production Registry**: `C:\Users\mcarls\.agent_continuity` (426 spool events in `events/`, `index.sqlite`)

## 1. Empirical Pre-Bootstrap & Startup Cost Breakdown

Measured via read-only inspection and disposable copies of `C:\Users\mcarls\.agent_continuity`:

| Component | Cold | Warm | Notes |
| --- | --- | --- | --- |
| `import agent_continuity.dispatcher_cli` | `89.62 ms` | — | CLI module + parser import |
| `PsutilProcessEnumerator().enumerate_processes()` | `6982.59–7201.77 ms` | `153.87 ms` | Windows ~712 processes; cold scan dominates pre-reservation delay when invoked per process |
| `CodexAdapter().detect_installation()` | `139.40 ms` | — | `codex --version` subprocess |
| `AgyAdapter().detect_installation()` | `333.07 ms` | — | `agy --version` subprocess |
| `ClaudeAdapter().detect_installation()` | `46.55 ms` | — | `claude --version` subprocess |
| `_resolve_environment(..., persist_local=True)` | `42.34 ms` | — | Environment lookup |
| `_new_launch_preview(...)` | `93.36 ms` | — | Preview construction |
| `prepare_start(apply=True)` (with legacy sync + fsync) | `3528.68 ms` | — | `_mutation_lock` + `_sync()` + `nt.fsync` (`~106–137 ms/event`) |
| `read_spool_events` (426 events, baseline) | `84.66 ms` | `68.98–74.91 ms` | Full `rglob` + open/read/JSON-parse/SHA-256 |
| `sync_from_spools` (426 events, baseline) | `1335.47 ms` | `89.52 ms` | Called 3x across `_start` -> `prepare_start` -> `_run_pane_locked` |
| Provider `READY` bootstrap (`codex exec` / `agy --print`) | `12–40+ s` | `12–40+ s` | Full LLM inference round-trip before launching interactive `resume` |

## 2. Incremental Registry Synchronization ([events.py](../agent_continuity/events.py), [materializer.py](../agent_continuity/materializer.py))

- **Fingerprint Identity & Race-Free Binding**:
  - `_read_and_validate_spool_file` opens each spool file once (`rb`), compares `os.fstat(fh.fileno())` before and after `fh.read()` against `os.stat(path, follow_symlinks=False)` while `fh` is still open across `(st_size, st_mtime_ns, st_ctime_ns, st_ino, st_dev)`, rejects concurrent mid-read or path-replacement mutations, validates JSON/schema, computes SHA-256 `checksum`, and binds the 5-tuple fingerprint directly to the validated bytes.
  - When `st_ino == 0` (or file identity cannot be established), readers conservatively decline caching rather than trusting weak metadata.
- **Per-Row Derived Table & Writer Exclusion (No Whole-Map JSON Serialization)**:
  - `SQLiteMaterializer` stores `(spool_file, size, mtime_ns, ctime_ns, ino, dev, checksum, event_id)` in `spool_file_fingerprints` inside the same SQLite transaction as `ingest_events`, `sync_from_spools`, and `rebuild_from_spools`, and serializes mutating/rebuild operations under a cross-process `.index.sqlite.lock` (`_writer_lock`) so `rebuild_from_spools` never unlinks live SQLite `-wal`/`-shm` sidecars while writers are active.
  - Unchanged warm `sync_from_spools()` returns from the read-only fast path with 0 file opens and 0 JSON parses; incremental appends update only the new row(s) in `O(K)`.
- **Immutable-Event Assumption & Full Verification/Recovery**:
  - Spool files under `events/<environment_id>/` are assumed immutable once written by `append_event`.
  - `sync_from_spools(verify_checksums=True)` and `rebuild_from_spools()` provide explicit full-verification and atomic SQLite recovery paths.
  - **Rebuild / Reader / Pre-Lock Scan Boundary**:
    - `rebuild_from_spools()` performs `read_spool_events()` *inside* `_writer_lock()` so concurrent `ingest_events()` writes cannot be dropped by a pre-lock scan snapshot.
    - `sync_from_spools()` keeps its unchanged read-only fast path lock-free, and when entering `_writer_lock()` checks `last_rebuild_at` and recomputes `deleted_keys` from the in-lock `spool_file_fingerprints` table (re-scanning if a rebuild occurred concurrently).
    - `_writer_lock()` excludes concurrent writers, not lock-free `_connect_ro()` readers: on Windows, an active reader holding `index.sqlite` / `-wal` / `-shm` prevents `os.replace` (`ContinuityError(MATERIALIZER_FAILED)` with staging cleanup and no live DB corruption); on POSIX, active readers retain their unlinked inode snapshot until closed.

## 3. Native Bootstrap Elimination Contract ([native_bootstrap.py](../agent_continuity/native_bootstrap.py))

| Provider | Verified Installed Mechanism | Schema / Protocol Evidence | Pre-First-Turn Resumability & Persistence | Safe to Enable Now |
| --- | --- | --- | --- | --- |
| **Claude** | `claude --session-id <UUID>` | Direct UUIDv4 CLI flag | Deterministic UUIDv4; no bootstrap model turn needed | **Yes** |
| **Codex (`0.172.0`)** | `codex app-server --stdio` (`initialize` -> `initialized` -> `thread/start`) | `ThreadStartParams` (`cwd`, `ephemeral: false`) -> `ThreadStartResponse` (`thread.id`, `thread.path`, `cwd`, `model`) | **Allocated != Resumable**: `thread/start` allocates `thread.id`; `can_authorize_interactive_resume` remains `False` until rollout/SQLite persistence (`rollout_id_verified` / `state_db_row`) AND bound `VerifiedLiveQualification` (`provider`, `version`, `runtime`, `mechanism`) | **No** (live resume gate pending) |
| **AGY (`1.5.18`)** | `agy acp --stdio` (`initialize` -> `session/new`) | ACP JSON-RPC returns `sessionId` without running a model turn | **Allocated != Resumable**: `can_authorize_interactive_resume` remains `False` until verified metadata (`metadata_id_verified`) AND bound `VerifiedLiveQualification` | **No** (live resume gate pending) |

- **Agent #1 Integration, LLMD-59 & LLMD-62 Initialization Boundary**:
  - `allocate_native_session(NativeBootstrapRequest(...)) -> NativeSessionAllocation` exposes a narrow typed contract distinguishing `native_session_id` (allocated identity), `persisted` (verified metadata evidence), `interactively_resumable`, `effective_provider_context`, and `can_authorize_interactive_resume`.
  - **LLMD-62 / LLMD-59 coordination**: `native_bootstrap.py` never resolves instruction files or claims delivery (`instruction_delivery_performed=False`, `supports_ordered_instruction_snapshots=True`, `requires_bootstrap_model_turn=False`, `workflow_init_mode="additive_without_extra_turn"`, `initial_prompt_delivery="one_time_on_attach"`). Agent #1's instruction-selection persistence resolves ordered Markdown instruction snapshots and delivers them alongside the one-time initial prompt at interactive attach/launch without extra model turns.
  - Timeout, `cancel_event`, saturated `stderr`, stalled `stdin`, malformed/conflicting JSON-RPC frames, or unclean helper shutdowns terminate the process tree, preserve bounded diagnostics (`uncertain_native_session_id`, `stderr_tail`, `shutdown_mode`), and set `fallback_prohibited=True` without falling back to `--last`, `--continue`, or recency guessing.
  - **Remaining live qualification / integration gates** (blocked here by no-live-model-trials policy): verify on live `codex-cli 0.172.0` and `agy 1.5.18` whether `codex resume <thread_id>` and `agy --conversation <sessionId>` (or ACP `session/load`) attach cleanly before the first model turn, and wire Agent #1's dispatcher integration.

## 4. Real-Provider Qualification Matrix & Procedure (Operator Approval)

| Provider & Version | Allocation Mechanism | Pre-Turn Persistence Check | Attach / Resume Check | LLMD-62 & LLMD-59 Boundary | Activation Gate |
| --- | --- | --- | --- | --- | --- |
| `claude 2.1.332` | `claude --session-id <UUID>` | Deterministic UUIDv4 CLI flag | Direct attach with `--session-id` | Ordered Markdown instruction snapshot + one-time initial prompt delivered at interactive attach (0 extra turns) | **Enabled** |
| `codex-cli 0.172.0` | `codex app-server --stdio` (`initialize` -> `initialized` -> `thread/start`) | Verify `thread.path` JSONL `session_meta.id` or `state_5.sqlite` `threads(id, cwd)` | Run `codex resume <thread_id>` in disposable `cwd` before first turn | Allocation sets `instruction_delivery_performed=False`; LLMD-62 snapshots + LLMD-59 prompt delivered once on attach | **Gated** (`VerifiedLiveQualification`) |
| `agy 1.5.18` | `agy acp --stdio` (`initialize` -> `session/new`) | Verify `session.json`/`metadata.json` ID match + installed `agy --version` | Run `agy --conversation <sessionId>` or ACP `session/load` before first turn | Allocation sets `instruction_delivery_performed=False`; LLMD-62 snapshots + LLMD-59 prompt delivered once on attach | **Gated** (`VerifiedLiveQualification`) |
