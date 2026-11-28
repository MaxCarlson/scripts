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

| Provider | Offline mechanism evidence | Persisted identity evidence | Effective workspace evidence | Live activation |
| --- | --- | --- | --- | --- |
| **Claude** | UUIDv4 is reserved for the direct `--session-id` invocation; the allocator does not start Claude. | **Not established by the allocator.** The UUID reservation is not a persisted provider session or transcript. | **Not observed by the allocator.** The eventual provider process has not run. | Not qualified by this procedure; separate interactive/transcript evidence is required. |
| **Codex (`0.172.0` candidate)** | Guarded app-server `initialize` -> `initialized` -> `thread/start`; no model turn is requested by allocation. | Exact `session_meta.payload.id` from a rollout under the configured Codex `sessions/` store, or an exact `state_5.sqlite` thread row. Arbitrary matching JSONL records and paths outside that store do not count. | Reported `cwd` or exact persisted rollout/SQLite cwd must match the request. Missing cwd is recorded as unknown; contradictory cwd blocks persistence/resume authorization. | **Disabled.** Requires exact version/runtime/executable, requested/effective permission, pre-turn persistence, workspace, and exact resume qualification. |
| **AGY (`1.5.18` candidate)** | Guarded ACP `initialize` -> `session/new`; the protocol request itself asks for no model turn. | Validate a safe ACP-returned `sessionId` and bounded, valid JSONL at the exact CLI transcript path `<agy_home>/brain/<sessionId>/.system_generated/logs/transcript.jsonl`. Identity follows from the returned ID plus its exact provider-store location; arbitrary metadata files are not accepted. | The documented transcript contract does not define a persisted workspace field. Cwd remains unknown and blocks attach authorization. AGY `session/new` permission effects are also unavailable. | **Disabled.** Requires isolated authenticated store, effective workspace and permission evidence, exact version/runtime/executable, pre-turn persistence, and exact resume qualification. |

- **Agent #1 Integration, LLMD-59 & LLMD-62 Boundary**:
  - `allocate_native_session(...)` distinguishes allocated ID, exact persisted identity, effective workspace evidence, provider context, and resumability. Allocator output never means the provider loaded instructions or received a prompt.
  - **Codex:** the guarded native path defers ordered instruction snapshots and the one-time prompt to the exact interactive attach; allocation sends neither. This attach path and provider-effective context remain unqualified live.
  - **AGY:** the managed native allocation path rejects one-time prompts and instruction snapshots before allocation. Existing fixed-bootstrap delivery is a different path and requires an initialization model turn; provider-effective loading and persistence across resume are not established.
  - **Claude:** the native allocator reserves a UUID only; it does not persist a provider session, prove cwd, or establish resumability. The managed interactive path can pass a one-time prompt, but live prompt delivery is unqualified. Claude workflow/custom instruction initialization remains unsupported and is refused.
  - The official [Antigravity Hooks contract](https://antigravity.google/docs/hooks) identifies the CLI transcript path under `~/.gemini/antigravity-cli/brain/<conversationId>/...` and says `SessionStart` fires before the first model invocation. It does not define that transcript's JSONL record schema or a persisted workspace field. The allocator therefore treats an exact transcript path as identity evidence only and leaves effective cwd unknown; do not enable AGY attach until a supported workspace receipt is qualified.
  - Timeout, `cancel_event`, saturated `stderr`, stalled `stdin`, malformed/conflicting JSON-RPC frames, or unclean helper shutdowns terminate the process tree, preserve bounded diagnostics (`uncertain_native_session_id`, `stderr_tail`, `shutdown_mode`), and set `fallback_prohibited=True` without falling back to `--last`, `--continue`, or recency guessing.
  - **Remaining live qualification / integration gates**: verify on live `codex-cli 0.172.0` and `agy 1.5.18` whether `codex resume <thread_id>` and `agy --conversation <sessionId>` (or ACP `session/load`) attach cleanly before the first model turn. Their inference-free allocation is implemented but remains disabled in LLMD until that gate is independently cleared.
  - **Current dispatcher adoption**: Claude's deterministic UUID allocation is persisted as a pending launch event with exact cwd and separate provider-persistence/resumability evidence. Guarded tests exercise reservation retry, interrupted launch recovery, and cwd mismatch refusal. This does not qualify live Claude creation or transcript association.

## Remaining guarded-start synchronization work

The guarded new-session CLI path now performs **21** registry syncs, down from the previous **27**-sync apply path. `tests/dispatcher_cli_test.py::test_guarded_new_start_keeps_registry_syncs_below_previous_27_call_path` traverses CLI start, bootstrap ID capture, durable association, and exact-session handoff with guarded provider adapter outputs. This measures synchronization calls, not provider startup latency or live provider behavior. Preserve the event-spool sync under the registry mutation lock before launch reservation and the execution-time refresh before provider handoff. Do not count `--dist=load` scheduling as proof of synchronization correctness.

## 4. Real-Provider Qualification Matrix & Procedure (Operator Approval)

| Provider & Version | Disposable check | Expected model turns | Provider-specific gate |
| --- | --- | --- | --- |
| Claude | Separate disposable `--session-id` launch, then exact transcript and resume inspection. UUID generation alone is not pre-turn persistence. | A harmless prompt requires one turn; creating/reserving the UUID requires none. | Workflow instructions unsupported. One-time prompt transport and exact resume need separate live evidence; this task does not enable or run them. |
| Codex | Guarded app-server allocation against a disposable `CODEX_HOME`; verify exact in-store session metadata and cwd, then exact `codex resume <thread_id>` in the same disposable worktree. | Allocation: zero. Empty interactive attach: expected zero. A harmless user prompt to prove a usable turn: one. | Match app-server version, executable, runtime, approval policy, sandbox, cwd, durable ID, and exact pre-turn resume. Keep dispatcher gate disabled until all match. |
| AGY | ACP allocation and `agy --conversation <sessionId>` must use a disposable authenticated provider home; verify safe ID and bounded exact transcript path, then capture a supported pre-turn workspace receipt and exact resume. The current implementation has no qualified workspace receipt and will not authorize attach. | ACP allocation: zero. Empty attach: expected zero. A harmless manually entered prompt to prove a usable turn: one. | Confirm provider-supported home isolation first; match ACP/provider version, executable, runtime, cwd, permissions, durable ID, and exact pre-turn resume. Native prompt/instruction delivery remains unsupported. |

### Commands reserved for a separately authorized live qualification

These commands were documented only; they were not run. A separate explicit approval must authorize provider subprocesses, disposable-profile authentication, creation of a provider session, exact-session attachment, and (if needed) one benign model turn. Keep the production dispatcher gate disabled throughout this manual check.

For Codex, first prepare a new disposable store and workspace, authenticate that disposable store through the provider's supported login flow, and then run the exact allocation request from this module directory:

```powershell
$qualRoot = Join-Path $env:TEMP 'llmd-native-qual-codex'
$env:CODEX_HOME = Join-Path $qualRoot 'codex-home'
$env:LLMD_QUAL_CWD = Join-Path $qualRoot 'workspace'
New-Item -ItemType Directory -Force -Path $env:CODEX_HOME, $env:LLMD_QUAL_CWD | Out-Null
codex login
$allocation = python -c "import json, os; from pathlib import Path; from agent_continuity.native_bootstrap import NativeBootstrapRequest, allocate_native_session; r=allocate_native_session(NativeBootstrapRequest(provider='codex', cwd=os.environ['LLMD_QUAL_CWD'], codex_home=Path(os.environ['CODEX_HOME']), expected_approval_policy='on-request', expected_sandbox_type='workspaceWrite', requested_settings={'approval_policy':'on-request','sandbox':'workspace-write'})); print(json.dumps(r.to_dict()))" | ConvertFrom-Json
$allocation | Select-Object status, native_session_id, persisted, interactively_resumable, effective_provider_context, persistence_evidence | ConvertTo-Json -Depth 8
if ($allocation.status -ne 'allocated' -or -not $allocation.persisted -or $allocation.effective_provider_context.workspace_status -ne 'verified' -or $allocation.effective_provider_context.permission_evidence.approval_policy.status -ne 'verified' -or $allocation.effective_provider_context.permission_evidence.sandbox_type.status -ne 'verified') { throw 'Codex allocation evidence did not qualify; do not attach or retry.' }
codex resume -C $env:LLMD_QUAL_CWD $allocation.native_session_id
```

Allocation and opening an empty exact-session attach are expected to use zero model turns. Sending one manually entered harmless prompt uses one turn and is optional; it is needed only if the separate review requires proof of a completed response. Do not pass `--prompt`, instruction files, or private repository content during this qualification. Capture the exact CLI version, executable, runtime, returned session ID, rollout/state DB evidence, cwd and effective approval/sandbox evidence with the result.

There is no safe AGY command sequence yet for a disposable authenticated store: the current implementation has no verified provider-supported store override and no transcript workspace receipt. Do not run `agy acp --stdio` against the ordinary user store as a substitute. Once both prerequisites are available and separately approved, the candidate exact-session command is `agy --conversation <sessionId>`; the native attach gate stays closed until a harmless empty attach proves exact pre-turn continuation and the effective workspace/permission evidence is captured. ACP allocation and empty attach are expected to use zero model turns; an optional manually entered harmless prompt uses one. AGY native prompt and instruction delivery remain unsupported.

Claude's UUID allocation is not provider session persistence. It remains outside the native attach qualification path; do not infer resumability or pre-turn workspace evidence from the reserved UUID.

## Final offline workload check — 2026-11-27

Re-ran the CLI preview and guarded apply paths against disposable registries containing exactly 426 synthetic spool event files. Seven warm `start -d -j` preview trials had a **545.13 ms** median after excluding the first cold trial (**2776.63 ms**); preview used **2** synchronization calls each. Three fresh-registry `start` trials used actual harmless Python bootstrap and interactive child processes, with no provider executable or model inference: median **6769.83 ms**, **25** synchronization calls each. The scan and publication boundary was enabled for all trials. The prior integrated benchmark reported 228.68 ms / 1 sync for preview and 3417.90 ms / 27 sync calls for apply under its stubbed guarded execution. These measurements are not strictly interchangeable: this final apply used actual Python child processes and a fresh registry per trial. Keep the older baseline as historical evidence and use this final result as the current reproducible workload measurement.
