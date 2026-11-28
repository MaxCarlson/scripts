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
  - `_read_and_validate_spool_file` opens each spool file once (`rb`), takes `os.fstat(fh.fileno())` before and after `fh.read()`, rejects concurrent mid-read mutations, validates JSON/schema, computes SHA-256 `checksum`, and binds `(st_size, st_mtime_ns, st_ctime_ns)` directly to the validated bytes.
  - Checking `(size, mtime_ns, ctime_ns)` catches same-size replacements even when `mtime_ns` is preserved (while staying consistent across Windows `os.scandir` `DirEntry.stat()` and `os.fstat()`).
- **Per-Row Derived Table (No Whole-Map JSON Serialization)**:
  - `SQLiteMaterializer` stores fingerprints in `spool_file_fingerprints` (primary key `spool_file`) inside the same SQLite transaction as `ingest_events`, `sync_from_spools`, and `rebuild_from_spools`.
  - Unchanged warm `sync_from_spools()` returns from the read-only fast path with 0 file opens and 0 JSON parses; incremental appends update only the new row(s) in `O(K)`.
- **Immutable-Event Assumption & Full Verification/Recovery**:
  - Spool files under `events/<environment_id>/` are assumed immutable once written by `append_event`.
  - `sync_from_spools(verify_checksums=True)` and `rebuild_from_spools()` provide explicit full-verification and atomic SQLite recovery paths.

## 3. Native Bootstrap Elimination Contract (Agent #1 Integration)

| Provider | Verified Installed Mechanism | Schema / Protocol Evidence | Pre-First-Turn Resumability & Persistence |
| --- | --- | --- | --- |
| **Claude** | `claude --session-id <UUID>` | Direct UUIDv4 CLI flag | Already supported without bootstrap model turn |
| **Codex (`0.172.0`)** | `codex app-server --stdio` (`initialize` -> `thread/start`) | `ThreadStartParams` (`cwd`, `ephemeral: false`) -> `ThreadStartResponse` (`thread.id`, `thread.path`, `cwd`, `model`) | **Allocated != Resumable**: `thread/start` allocates `thread.id`; interactive `codex resume <thread_id>` requires persistence evidence (`thread.path` rollout JSONL `session_meta` or `~/.codex/state_5.sqlite` `threads` row) |
| **AGY (`1.5.18`)** | `agy acp --stdio` (`initialize` -> `session/new`) | ACP JSON-RPC returns `sessionId` without running a model turn | **Allocated != Resumable**: verify ACP `session/load` or `~/.gemini/antigravity-cli` persistence before assuming `agy --conversation <sessionId>` can resume pre-turn |

- **Cancellation, Crash Recovery & Remaining Live Qualification Gates**:
  - Timeout or non-zero exit during `app-server` / `acp` allocation must kill the helper process and abort reservation without falling back to `--last`, `--continue`, or recency guessing.
  - **Remaining live qualification gates** (blocked here by no-live-model-trials policy): verify on live `codex-cli 0.172.0` and `agy 1.5.18` whether `codex resume <thread_id>` and `agy --conversation <sessionId>` attach cleanly before the first model turn or require `thread/resume` / `--prompt-interactive`.
