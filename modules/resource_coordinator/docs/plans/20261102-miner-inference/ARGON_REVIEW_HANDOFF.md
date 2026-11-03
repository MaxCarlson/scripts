# Independent Argon Adversarial Review Handoff Package
**Plan ID:** `miner-inference-coordination-20261102`  
**Branch:** `feature/miner-inference-coordination-20261102`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\miner-inference-coordination-20261102`  
**Host Platform:** Windows 11 Pro (win32, Python 3.12.10, PowerShell 7.5 / `pwsh`)  
**Target Upstream:** LM Studio `127.0.0.1:1234` (resident model: `qwen38-27b-q4km` alias `qwen38_23GB`)  
**Companion Mining Repo:** `C:\Users\mcarls\src\Mining` (branch `master` at commit `9c36ed042ec68fba956846917ede2d04678c5230`)

---

## 1. Mission & Scope

This package transfers the hardened, remediated implementation of request-driven miner interruption for local LLM inference to an independent, adversarial reviewer ("Argon").

The core objective is to ensure that:
1. GPU mining (`KRig` or `SRBMiner`) runs only when zero protected local-model inference requests are pending, executing, or unresolved.
2. Arrival of a protected inference request atomically increments the pending reservation count, cancels any scheduled restart timer, and verifies that the miner process is completely stopped **before** forwarding bytes to LM Studio.
3. Mining remains stopped while any protected request is outstanding.
4. Following the final verified completion of protected inference, an exact 10.0-second monotonic idle cooldown is observed.
5. If any request arrives during that 10.0-second interval, the restart intent is immediately cancelled.
6. If the 10.0-second cooldown expires without interruption, no holds remain, and no errors occurred, the coordinator-owned miner process is restarted.
7. **No GPU-utilization polling or heuristics are used** to determine whether inference is occurring. Request admission, lease accounting, verified completion, and OS process group ownership are the sole control mechanisms.

---

## 2. Architecture & Authority Boundaries

```text
Direct inference:
    Client (OpenCode / Benchmark / IDE)
      └─► Resource Coordinator (:1235)
            └─► LM Studio Upstream (:1234)

Monitored inference:
    Client (OpenCode / Benchmark / IDE)
      └─► LLM Monitor (:8788 or :8789)
            └─► Resource Coordinator (:1235)
                  └─► LM Studio Upstream (:1234)
```

- **Sole Control Authority:** The Resource Coordinator gateway (`:1235`) is the sole authority for deciding when mining stops or restarts.
- **Fail-Closed Gate:** All inference admission routes pass through `LMStudioGateway._proxy_with_coordination`. If lease reservation, process stopping, pre-forward state persistence, or upstream connection fails, traffic is rejected (500/503), leases are cleaned up, and restarts remain inhibited.
- **Lease Manager Invariants:** Leases track resources (`gpu.inference`, `gpu.model_loading`). Pending and active lease counters are guarded by `asyncio.Lock`.
- **Single-Instance Authority:** Enforced across the entire host via `SingleInstanceLock` backed by OS-level file locking (`msvcrt.locking` on Windows, `fcntl.flock` on POSIX).

---

## 3. Hardware & Live Environment Safeguards

During all phases of development, testing, and independent review, the following boundaries must remain intact:
1. **GPU Power Limits and Overclocking:**
   - The host NVIDIA GeForce RTX 5090 is configured with a 600W max power limit.
   - The coordinator **never** executes `nvidia-smi -pl`, does not mutate power limits, and does not alter GPU clocks.
2. **Foreign Process Non-Interference:**
   - The coordinator never stops, signals, or adopts processes not started by its own instance (`adopt_external: false`).
   - If an unmanaged miner was launched manually via PowerShell, the coordinator refuses to touch it.
3. **Host Resident Processes:**
   - Active host processes—including OpenCode workers (PIDs `47108`, `63836`), LLM Monitor (`:8789`, PID `58828`), and LM Studio (`:1234`)—are never terminated or signaled.
4. **Offline Test Isolation:**
   - All regression suites run with in-memory mocks, isolated temporary directories, or disposable test scripts (`windows_miner_helper.vbs`).

---

## 4. Remediation Findings & Solutions

The independent review identified several critical edge cases in concurrency, persistence, and process management. Each has been addressed directly with test-driven regression coverage:

### Finding 1: Durable Journal Missing-State Safety
- **Root Cause:** A missing journal file on disk was treated as an implicit clean startup. If a journal file was accidentally deleted or unmounted following a crash, the coordinator would boot without replaying unverified pre-forward requests, permitting an unsafe miner start.
- **Chosen Solution:** Modified `CoordinatorService.start()` to fail closed with `RuntimeError` if `state_persistence_path` is configured and the file is missing, unless `first_boot=True` is explicitly passed. Added `StateCodec.initialize(path)` for explicit bootstrap.
- **Alternative Considered:** Auto-creating an empty journal on every boot was rejected because it conceals crash loss.
- **Files Changed:** `core/durable_state.py`, `core/service.py`, `cli.py`.
- **Demonstrating Test:** `test_missing_state_journal_refuses_startup_unless_first_boot` in `test_remediation_findings.py`.

### Finding 2: Reservation Cleanup on Journal Write Failure
- **Root Cause:** In `gateway._proxy_with_coordination`, `lease_mgr.reserve()` entered the reservation before `StateCodec.record_request_phase(..., RESERVED)`. If the disk write failed (e.g. disk full or I/O error), an exception was raised outside the guarded block, leaving `pending_count` permanently incremented and leaking a restart inhibition.
- **Chosen Solution:** Enclosed `reservation_cm.__aenter__()` and the initial journal write in a comprehensive `try/finally` block. Any journal write failure triggers `reservation_cm.__aexit__`, decrementing `pending_count` back to 0.
- **Files Changed:** `adapters/lmstudio/gateway.py`.
- **Demonstrating Test:** `test_reservation_cleanup_on_journal_write_failure` in `test_remediation_findings.py`.

### Finding 3: Startup Recovery & Durable Resolution of Uncertain Requests
- **Root Cause:** Clearing in-memory holds via `/_coordinator/recover` only updated memory. Subsequent service restarts reloaded the un-terminalized `POSSIBLY_FORWARDED` or `UNCERTAIN` requests from disk and re-inhibited restarts. Furthermore, if a service was configured with `start_miner_on_ready=True`, startup failed closed into `FAILED`, preventing operator recovery endpoints from being served.
- **Chosen Solution:**
  1. Implemented `StateCodec.resolve_unresolved_requests()` which transitions all unresolved requests to `TERMINAL_VERIFIED` with operator attribution (`resolved_by: operator_override:<operator>:<reason>`).
  2. Wired resolution into `handle_coordinator_recover`.
  3. When `start_miner_on_ready=True` encounters an existing inhibition on startup, it logs a warning and holds the miner stopped while allowing the service to enter `READY` and accept operator recovery.
- **Files Changed:** `core/durable_state.py`, `core/service.py`, `adapters/lmstudio/gateway.py`.
- **Demonstrating Test:** `test_recovery_resolves_persistent_unresolved_requests` in `test_remediation_findings.py`.

### Finding 4: Single-Instance Lock Correctness & Descriptor Leaks
- **Root Cause:** `SingleInstanceLock.release()` previously unlinked the lock file upon release. On Windows and POSIX, deleting a lock file creates a severe race: another process can open the existing file descriptor and acquire the lock, after which the exiting process unlinks it, breaking mutual exclusion for subsequent openers. Additionally, exceptions during `os.open` or `locking` leaked open file descriptors.
- **Chosen Solution:** Removed `os.unlink()`. Lock file identity remains permanent on disk. Wrapped acquisition in `try/except` with explicit `os.close(fd)` on failure. Released the lock in `CoordinatorService.start()` if startup fails closed.
- **Files Changed:** `core/lock.py`, `core/service.py`.
- **Demonstrating Test:** `test_multiprocess_lock_contention` in `test_remediation_findings.py`.

### Finding 5: Race-Safe Continuous Miner Supervision & Backoff Cancellation
- **Root Cause:**
  1. `handle_unexpected_exit_backoff` slept while holding `self._lock`, blocking incoming requests or shutdown signals.
  2. After waking up from backoff sleep, it started the process without re-checking if new inference requests arrived during backoff.
  3. No continuous background supervision task existed in `CoordinatorService` to monitor managed processes.
- **Chosen Solution:**
  1. Released `self._lock` during backoff sleep.
  2. Re-acquired `self._lock` after sleep and re-verified that `active_count == 0`, `pending_count == 0`, and no inhibitions or coordinator stops occurred. If not idle, restart is aborted immediately.
  3. Added `_run_supervision_loop()` in `CoordinatorService` that periodically checks processes configured for restart and initiates bounded backoff recovery.
- **Files Changed:** `core/processes.py`, `core/service.py`.
- **Demonstrating Tests:** `test_backoff_aborted_by_reservation_arrival`, `test_continuous_supervision_loop_recovers_crashed_process` in `test_remediation_findings.py`.

### Finding 6: Mining Launcher and Manifest Compatibility
- **Root Cause:** Committed `start-prl.ps1` in `MaxCarlson/Mining` does not accept `-KrigCoreClockMHz`. Passing it caused preview invocations to fail, and `manifest.py` silently fell back to an internal argument generator that diverged from the launcher script.
- **Chosen Solution:** Removed `-KrigCoreClockMHz` when calling `start-prl.ps1 -Preview`. Replaced silent fallback with explicit `RuntimeError` if `-Preview` fails. Aligned fallback arguments with the committed launcher script.
- **Files Changed:** `adapters/miners/manifest.py`.
- **Demonstrating Test:** `test_manifest_preview_failure_raises_explicit_error` in `test_remediation_findings.py`.

### Finding 7: Honest Acceptance Harness Mode Handling
- **Root Cause:** `AcceptanceHarness` previously ran all modes against in-memory mocks without validating flags or recording verification levels.
- **Chosen Solution:**
  1. Added `process_backend`, `upstream_type`, and `verification_level` to `AcceptanceReport`.
  2. Added disposable helper script `windows_miner_helper.vbs`. When `mode == "disposable_helper"` on Windows, harness runs real OS processes via `cscript.exe //NoLogo ... windows_miner_helper.vbs` under `WindowsProcessBackend`.
  3. Required `allow_live_lmstudio=True` and `allow_real_miner=True` for `mode == "live"`, failing closed with `ValueError` otherwise.
- **Files Changed:** `acceptance_harness.py`, `core/processes.py`, `adapters/miners/windows_miner_helper.vbs`.
- **Demonstrating Tests:** `test_acceptance_harness_live_mode_requires_explicit_authorization`, `test_acceptance_report_metadata` in `test_remediation_findings.py`.

### Finding 8: CLI, Runbook, and Documentation Corrections
- **Root Cause:** `RUNBOOK.md` instructed users to run `cli.py start` (which did not exist; command is `serve`) and referenced `/coordinator/...` endpoints instead of `/_coordinator/...`. In `cli.py`, `cmd_serve` had mismatched keyword arguments (`start_miner_on_startup` and `drain_timeout`).
- **Chosen Solution:** Fixed keyword arguments in `cli.py` (`start_miner_on_ready`, `drain_timeout_seconds`, `--first-boot`), and updated all endpoint paths and commands in `RUNBOOK.md` and `PHASE_03_ACCEPTANCE_PLAN.md`.
- **Files Changed:** `cli.py`, `docs/plans/20261102-miner-inference/RUNBOOK.md`, `docs/plans/20261102-miner-inference/PHASE_03_ACCEPTANCE_PLAN.md`.

---

## 5. Durable State & Crash Recovery Specification

| Record Type | Durable Moment | Recovery Replay Behavior |
|---|---|---|
| `RESERVED` | Before upstream byte transmission | Replayed on boot as `RestartInhibition` on resource |
| `POSSIBLY_FORWARDED` | Immediately before forwarding to LM Studio | Replayed on boot as `RestartInhibition` on resource |
| `TERMINAL_VERIFIED` | After receipt of `[DONE]`, complete body, or verified upstream error | Resource remains restart-eligible |
| `UNCERTAIN` | On premature socket disconnect or truncated stream | Latches `RestartInhibition`; requires authenticated operator recovery |
| `OPERATOR_RESOLVED` | On authenticated `POST /_coordinator/recover` | Preserves `previous_phase` and operator attribution; clears startup inhibition |
| `RestartInhibition` | Latched on crash, abort, or uncertain completion | Persisted to journal; blocks all automatic process restarts |

### Recovery Flow
1. **Operator Override:** Operator inspects LM Studio / hardware, then issues:
   `POST /_coordinator/recover?resource=gpu.inference`
   with Bearer token, `override: true`, `operator`, and `reason`.
2. **Atomic Resolution:** Inside `LeaseManager.clear_inhibition(before_clear=...)`, `StateCodec.resolve_unresolved_requests()` transitions unresolved records to `OPERATOR_RESOLVED` on disk **before** clearing the in-memory hold or starting cooldown. If disk persistence fails, the in-memory inhibition remains latched.
3. **Clean Restart:** Future coordinator reboots read a clean journal without re-imposing stale inhibitions.

---

## 6. Concurrency & Race-Safety Invariants

1. **Reservation Before Forward:** `pending_count` is incremented under lock before checking miner status or dispatching upstream bytes.
2. **Immediate Cancellation:** Any arrival during the 10.0s cooldown cancels the timer callback before any await.
3. **Debounce Interval:** Cooldown timer uses monotonic time (`time.monotonic()`). Cooldown duration is strictly 10.0 seconds.
4. **Watchdog Interruption:** If a miner exits unexpectedly, backoff sleep (1s, 2s, 4s) releases the supervisor lock. Before restarting, all invariants (`active == 0`, `pending == 0`, `not is_inhibited`) are re-verified. Any inference request arriving during backoff cancels the restart.
5. **Crash Loop Exhaustion:** After 3 consecutive unexpected exits during idle, the supervisor permanently latches a `RestartInhibition` on `gpu.inference`.

---

## 7. Process Supervision & Windows Ownership Contracts

- **Process Identity:** Managed processes are tracked by exact PID and OS process creation time (`psutil.Process(pid).create_time()`).
- **Signaling:** Clean termination sends `CTRL_BREAK_EVENT` via Windows console process groups (`GenerateConsoleCtrlEvent`).
- **Child Tree Cleanup:** If force termination is configured, `WindowsProcessBackend` recursively enumerates child descendants and terminates them before completing the stop barrier.
- **No Foreign Adoption:** `adopt_external: false` prevents the coordinator from killing external processes sharing executable names.

---

## 8. Acceptance Harness & Supervised Test Sequence Modes

| Mode | Backend | Upstream | Verification Level | Safeguards |
|---|---|---|---|---|
| `simulated` | `FakeProcessBackend` | Mock Starlette App | `unit_simulation` | Pure in-memory offline execution |
| `disposable_helper` | `WindowsProcessBackend` (`cscript.exe`) | Mock Starlette App | `os_process_contract` | Real Windows process group signaling & tree cleanup |
| `live` | `WindowsProcessBackend` (`krig.exe`) | LM Studio (`:1234`) | `live_hardware` | Requires explicit `--allow-live-lmstudio` and `--allow-real-miner` |

The 5 acceptance trials:
- **T01:** Single Request Stop Before Forward and 10s Cooldown Resumption
- **T02:** Cooldown Interruption and Debounce (Arrival at T+5s/T+9s)
- **T03:** Concurrent Overlapping Requests & Last-Request Completion Detection
- **T04:** Streaming SSE Verification with `data: [DONE]` Terminal Detection
- **T05:** Error Handling, Truncated Streams, and Restart Inhibition Latching

---

## 9. Verification Evidence & Test Commands

### Test Execution Commands
```powershell
# Set PYTHONPATH for worktree
$env:PYTHONPATH = "C:\Users\mcarls\src\scripts\.worktrees\miner-inference-coordination-20261102\modules\resource_coordinator"

# Run remediation regression tests
python -m pytest modules/resource_coordinator/tests/test_remediation_findings.py -v

# Run full resource_coordinator test suite
python -m pytest modules/resource_coordinator/tests
```

### Verified Test Suite Results
- `modules/resource_coordinator`: **298 passed, 4 skipped in 18.15s** (including 10 Argon adversarial review tests in `test_argon_adversarial_review.py`).
- `modules/llm_monitor`: **253 passed, 2 skipped in 10.96s**.
- Zero Failures, Zero Errors.
- Complete adversarial review report recorded in `ARGON_REVIEW_RESULTS.md`.

---

## 10. Recommended Next Actions for Independent Argon Review

1. **Adversarial Race Review:**
   - Review `core/processes.py` (`handle_unexpected_exit_backoff`) and `adapters/lmstudio/gateway.py` (`_proxy_with_coordination`) under simulated high-contention task scheduling.
2. **Durable Journal Corruption Review:**
   - Inject malformed JSON or partial disk writes into `coordinator_state.json` and verify fail-closed startup behavior.
3. **Disposable Helper Acceptance:**
   - Execute `AcceptanceHarness(mode="disposable_helper", cooldown_seconds=10.0)` on the Windows host to observe genuine `cscript.exe` process termination and creation-time verification.
4. **Supervised Live Pilot Execution:**
   - With explicit human operator presence, execute a supervised single-request test against resident LM Studio `127.0.0.1:1234` and verify GPU VRAM protection.
