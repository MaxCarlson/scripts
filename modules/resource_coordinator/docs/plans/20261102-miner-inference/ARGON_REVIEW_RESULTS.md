# Independent Adversarial Review Results (Argon) — Miner / Local LLM Coordination

**Plan ID:** `miner-inference-coordination-20261102`  
**Reviewer Role:** Independent Adversarial Reviewer (Argon)  
**Review Timestamp:** 2026-11-02T12:35:00-08:00  
**Repository:** `MaxCarlson/scripts`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\miner-inference-coordination-20261102`  
**Branch:** `feature/miner-inference-coordination-20261102`  
**Baseline Audited Commit:** `d097f1c6937670801ac910418d6d1925fc76532a`  

---

## 1. Executive Summary & Readiness Decision

An independent adversarial source audit and test reproduction was conducted against commit `d097f1c6937670801ac910418d6d1925fc76532a` on `feature/miner-inference-coordination-20261102`.

Rather than relying on prior test claims, the review audited the implementation line-by-line against the 11 core correctness invariants and priority areas A–E. The audit uncovered **five substantive defects** across acceptance-mode integrity, operator recovery ordering, watchdog restart concurrency, runtime journal disappearance handling, and manual pause persistence.

All five defects were:
1. **Reproduced** via 10 deterministic adversarial regression tests in `modules/resource_coordinator/tests/test_argon_adversarial_review.py` (observed failing in RED phase).
2. **Remediated** with minimal, race-safe fixes reusing existing lock/condition primitives (`LeaseManager._condition`, `LeaseManager.run_if_idle`, `StateCodec`).
3. **Verified** across the full `resource_coordinator` suite (**298 passed, 4 skipped**) and the full `llm_monitor` suite (**253 passed, 2 skipped**), including real Windows OS process-contract execution via `cscript.exe //NoLogo windows_miner_helper.vbs`.

**Readiness Verdict:** **READY FOR SUPERVISED REAL-HARDWARE ACCEPTANCE.**

---

## 2. Confirmed Findings, Root Causes, Fixes, and Regression Tests

### Finding A — `AcceptanceHarness` Simulated Fallback in `live` Mode & Mode Validation (HIGH)

- **Location:** `resource_coordinator/acceptance_harness.py`
- **Root Cause:**
  1. `AcceptanceHarness.__init__()` set report metadata `process_backend="windows_miner"`, `upstream_type="live_lmstudio"`, and `verification_level="live_hardware"` when `mode="live"` (with `allow_live_lmstudio=True, allow_real_miner=True`). However, `_build_test_harness()` only branched on `if self.mode == "disposable_helper" and os.name == "nt":` and fell into `else:`, constructing `FakeProcessBackend` and `mock_upstream_app`. Running `run_all()` in `live` mode executed pure in-memory simulation while producing an acceptance report claiming `verification_level="live_hardware"`.
  2. Unsupported `mode` strings silently fell into the `simulated` branch instead of raising `ValueError`.
  3. In `disposable_helper` mode on Windows, trials slept `cooldown + 0.05s` and immediately asserted `backend.running is True`, which raced real Windows `cscript.exe` process creation latency inside the background cooldown callback.
- **Minimal Fix Implemented:**
  - Validated `mode in {"simulated", "disposable_helper", "live"}` in `AcceptanceHarness.__init__()`, raising `ValueError` otherwise.
  - Enforced `os.name == "nt"` for `mode == "disposable_helper"`.
  - Refused simulated fallback when `mode == "live"`: required an explicit `miner_process_config` (`backend == "windows"`) or raised `RuntimeError`, and wired `_build_test_harness()` to never construct `FakeProcessBackend` or `mock_upstream_app` in `live` mode.
  - Added bounded post-cooldown polling (`_wait_for_restart`) so real OS process spawn in `disposable_helper` mode is verified deterministically.
- **Reproducing & Verifying Tests:**
  - `TestFindingAAcceptanceHarnessIntegrity::test_finding_a_rejects_invalid_mode_and_refuses_live_simulated_fallback`
  - `TestFindingAAcceptanceHarnessIntegrity::test_finding_a_disposable_helper_real_windows_cscript_execution` (executes all 5 acceptance trials against real Windows `cscript.exe` processes).

---

### Finding B — Non-Atomic Operator Recovery Ordering & Conflation of Override with `TERMINAL_VERIFIED` (CRITICAL)

- **Location:** `adapters/lmstudio/gateway.py` (`handle_coordinator_recover`), `core/leases.py` (`clear_inhibition`), `core/durable_state.py` (`RequestPhase`, `StateCodec.resolve_unresolved_requests`)
- **Root Cause:**
  1. `handle_coordinator_recover()` called `await self.lease_mgr.clear_inhibition(...)` **before** `StateCodec.resolve_unresolved_requests(...)`. When disk persistence failed (`OSError`), the in-memory inhibition was already cleared and the idle cooldown timer had already started—permitting the miner to restart in memory while durable state still held unresolved requests.
  2. `StateCodec.resolve_unresolved_requests()` overwrote `req.phase` to `RequestPhase.TERMINAL_VERIFIED.value`, erasing the audit distinction between genuinely verified completion and an unverified operator override, and discarding the prior phase (`possibly_forwarded` / `uncertain`).
- **Minimal Fix Implemented:**
  - Added `RequestPhase.OPERATOR_RESOLVED = "operator_resolved"` to `RequestPhase`.
  - Updated `StateCodec.resolve_unresolved_requests()` to transition unresolved requests (`RESERVED`, `POSSIBLY_FORWARDED`, `UNCERTAIN`) to `RequestPhase.OPERATOR_RESOLVED.value` while preserving `req.details["previous_phase"] = req.phase`, `req.details["resolved_by"]`, and `req.details["resolved_at"]`.
  - Added a `before_clear: Optional[Callable[[], None]] = None` hook to `LeaseManager.clear_inhibition()`, executed inside `async with self._condition:` after verifying zero active/pending requests and **before** popping `self._inhibitions[resource]` or starting cooldown.
  - Wired `StateCodec.resolve_unresolved_requests` into `before_clear` in `handle_coordinator_recover()`, returning HTTP 500 on `(OSError, ValueError)` while keeping in-memory inhibition intact and preventing cooldown startup.
- **Reproducing & Verifying Test:**
  - `TestFindingBOperatorRecoveryAtomicityAndPhase::test_finding_b_operator_recovery_journal_failure_preserves_in_memory_inhibition`

---

### Finding C — Watchdog Restart Race Against New Reservations, Cooldown Blindness, Lock-Order Inversion, and Spurious Launch of Unstarted Processes (CRITICAL)

- **Location:** `core/processes.py` (`ProcessSupervisor.handle_unexpected_exit_backoff`), `core/service.py` (`CoordinatorService._run_supervision_loop`), `core/leases.py` (`LeaseManager.run_if_idle`)
- **Root Cause:**
  1. **Post-backoff race window:** After `await asyncio.sleep(backoff)`, `handle_unexpected_exit_backoff()` checked `active_count` and `pending_count` without holding `lease_manager._condition`, then awaited `self.backend.status()` and `self.backend.start()`, leaving a race window where a new reservation could interleave with process launch.
  2. **Cooldown blindness:** Neither `handle_unexpected_exit_backoff()` nor `_run_supervision_loop()` checked `lease_manager.is_cooling_down(resource)`. A process that crashed before or during the 10-second post-inference cooldown could be restarted by the watchdog before the 10-second quiet window expired.
  3. **Lock-order inversion:** Canonical lock order in `PolicyEngine._on_resource_idle` is `lease_manager._condition -> supervisor._lock`. `handle_unexpected_exit_backoff()` held `supervisor._lock` while awaiting `lease_manager.inhibit_restart()` (which acquires `lease_manager._lock`).
  4. **Spurious launch of never-started processes:** When `CoordinatorService` started with `start_miner_on_ready=False`, `_run_supervision_loop()` saw the never-started process in `STOPPED` state with `was_stopped_by_coordinator == False` and treated it as an unexpected crash, launching it after `supervision_poll_interval`.
  5. **Retry counter inflation on pre-empted backoff:** When an inference reservation arrived during backoff sleep, `consecutive_unexpected_exits` remained incremented even though the restart was aborted due to legitimate inference activity.
- **Minimal Fix Implemented:**
  - Added `check_self_cooldown: bool = False` to `LeaseManager.run_if_idle()`.
  - Updated `handle_unexpected_exit_backoff()` to check `lease_manager.is_cooling_down(resource)` before backoff, release `self._lock` before calling `await lease_manager.inhibit_restart(...)` on retry exhaustion, and execute the post-backoff check and `backend.start()` inside `await lease_manager.run_if_idle(resource, _restart_if_still_stopped, check_self_cooldown=True)` (preserving `lease_manager._condition -> self._lock` ordering). If pre-empted during backoff, `consecutive_unexpected_exits` is decremented back.
  - Tracked `_has_started` on `ProcessSupervisor` and gated `_run_supervision_loop()` on `supervisor._has_started` and `not self.system.lease_mgr.is_cooling_down(res)`.
- **Reproducing & Verifying Tests:**
  - `TestFindingCWatchdogRestartRaces::test_finding_c_supervision_loop_does_not_start_never_started_process`
  - `TestFindingCWatchdogRestartRaces::test_finding_c_watchdog_respects_active_cooldown`
  - `TestFindingCWatchdogRestartRaces::test_finding_c_watchdog_race_at_process_start_barrier_after_backoff`
  - `TestFindingCWatchdogRestartRaces::test_finding_c_controllable_barrier_serializes_start_with_incoming_reservation`

---

### Finding D — Runtime Journal Disappearance & Uninhibited Terminal Persistence Failure (CRITICAL)

- **Location:** `core/durable_state.py` (`StateCodec.record_*`, `clear_inhibition`, `resolve_unresolved_requests`), `adapters/lmstudio/gateway.py` (`_proxy_with_coordination` cleanup)
- **Root Cause:**
  1. `StateCodec.record_request_phase()`, `record_process_state()`, `record_inhibition()`, `clear_inhibition()`, and `resolve_unresolved_requests()` used `state = cls.load(target) if target.exists() else CoordinatorState()`. If an initialized journal file disappeared at runtime, the next state transition silently created a fresh `CoordinatorState()`, erasing all prior unresolved requests and persisted inhibitions.
  2. In `gateway.py` (`cleanup()`), if `StateCodec.record_request_phase(..., TERMINAL_VERIFIED)` raised an `OSError` or `FileNotFoundError` after a forwarded request completed, the exception was only logged; no in-memory `RestartInhibition` was latched, allowing the 10-second cooldown to start and restart the miner despite the unrecorded terminal state.
- **Minimal Fix Implemented:**
  - Removed `if target.exists() else CoordinatorState()` from all runtime mutation methods on `StateCodec`; all runtime mutations now call `cls.load(target)` directly and raise `FileNotFoundError` if the journal is missing. Only `StateCodec.initialize()` can create a new journal file.
  - Updated `LMStudioGateway._proxy_with_coordination()` (`cleanup()`) so that any exception raised while recording the terminal request phase latches `await self.lease_mgr.inhibit_restart(...)` in memory before releasing the reservation.
- **Reproducing & Verifying Tests:**
  - `TestFindingDDurableJournalIntegrityAndTerminalFailure::test_finding_d_runtime_journal_disappearance_raises_and_latches_inhibition`
  - `TestFindingDDurableJournalIntegrityAndTerminalFailure::test_finding_d_terminal_write_oserror_latches_in_memory_inhibition`

---

### Finding E — Manual Pause (`is_manual_override`) Not Persisted Across Coordinator Restarts (HIGH)

- **Location:** `core/durable_state.py` (`PersistedProcess`, `StateCodec.record_process_state`, `reconcile_startup_state`), `core/processes.py` (`ProcessSupervisor`), `core/service.py` (`CoordinatorService.start`, `_freeze`, `stop`), `config.py` (`build_system`)
- **Root Cause:**
  1. `PersistedProcess` lacked an `is_manual_override` field, `ProcessSupervisor` never called `StateCodec.record_process_state()`, and `reconcile_startup_state()` never restored `is_manual_override` onto `supervisors`.
  2. `CoordinatorService._freeze()` called `supervisor.set_manual_override(True)` during normal shutdown, and `CoordinatorService.start()` with `start_miner_on_ready=True` attempted to launch a manually overridden miner and failed startup instead of skipping launch while preserving `READY` state.
- **Minimal Fix Implemented:**
  - Added `is_manual_override: bool = False` to `PersistedProcess` and `StateCodec.record_process_state()`, and restored `was_stopped_by_coordinator` and `is_manual_override` onto supervisors in `reconcile_startup_state()`.
  - Wired `state_persistence_path` into `ProcessSupervisor` so `start()`, `stop()`, and operator `set_manual_override(paused, persist=True)` persist process state to the journal, while internal service `_freeze()` uses `set_manual_override(True, persist=False)` and shutdown stops use `origin="shutdown"`.
  - Updated `CoordinatorService.start()` to skip `start_miner_on_ready` / `start_process_on_ready` with a warning when `is_manual_override` is active.
- **Reproducing & Verifying Test:**
  - `TestFindingEManualPausePersistence::test_finding_e_manual_pause_persists_across_restarts_and_inference`

---

## 3. Verification Commands & Exact Results

| Suite | Command | Result |
|---|---|---|
| **Argon Adversarial Review Suite** | `python -m pytest modules/resource_coordinator/tests/test_argon_adversarial_review.py -v` | **10 passed in 8.3s** |
| **Supervised Acceptance Readiness Suite** | `python -m pytest modules/resource_coordinator/tests/test_supervised_acceptance_readiness.py -v` | **10 passed in 9.50s** |
| **Full Resource Coordinator Suite** | `python -m pytest modules/resource_coordinator/tests` | **308 passed, 4 skipped in 25.4s** |
| **Full LLM Monitor Suite** | `python -m pytest modules/llm_monitor/tests` | **253 passed, 2 skipped in 18.4s** |

### Host Safety Verification
- No real `krig-miner.exe` or `SRBMiner-MULTI.exe` processes were launched.
- No GPU power limits (`nvidia-smi -pl`) or clock settings were modified on the host RTX 5090.
- Resident LM Studio (`127.0.0.1:1234`), LLM Monitor (`127.0.0.1:8789`, PID `58828`), OpenCode workers (`47108`, `63836`), and the user's external `krig-miner.exe` session (PID `69988`) remained undisturbed.
- Companion repository `C:\Users\mcarls\src\Mining` remained untouched.

---

## 4. Addendum — Supervised Hardware Acceptance Readiness & `origin/main` Divergence Analysis

### 4.1 Six Focused Corrections Implemented
1. **Guaranteed Cleanup in `finally` (`acceptance_harness.py`):**
   - Refactored `_run_trial_1` through `_run_trial_5` to always invoke `_cleanup_trial_harness()` inside `finally:`, stopping `CoordinatorService`, verifying `backend.status().state == ProcessState.STOPPED`, and inspecting all recorded Windows `(pid, create_time)` identities and recursive descendants via `psutil`.
   - Any unverified stop during cleanup forces `t.status = "FAIL"` and records `t.metrics["cleanup_verified_stopped"] = False`.
2. **Realistic Live Testing & Read-Only Model Discovery (`acceptance_harness.py`):**
   - Added `discover_live_model()` querying `GET /api/v0/models` first to select a resident `state == "loaded"` LLM/VLM (`qwen38_23GB`), failing closed if no model is loaded so live acceptance never triggers an unintended model swap. Falls back to `GET /v1/models` when `/api/v0/models` returns 404.
   - Enforced `cooldown_seconds >= 10.0` in `live` mode and separated mock-only synthetic fault injection (`T05`) from live trials (`T01`–`T04`).
3. **Durable Safety (`acceptance_harness.py`):**
   - Wired isolated, explicitly initialized per-trial durable journals (`StateCodec.initialize`) and `SingleInstanceLock` ownership into `_build_test_harness()`.
4. **Correct Failure Behavior & Telemetry (`acceptance_harness.py`):**
   - Recorded `model_id`, `initial_pid`, `initial_create_time`, `stopped_before_forward_verified`, `observed_exit_during_inference`, `inference_result`, `cooldown_target_seconds`, `cooldown_elapsed_seconds`, `restarted_pid`, `restarted_create_time`, `cleanup_verified_stopped`, and `descendants_verified_stopped` in `TrialEvidence.metrics`.
5. **Operational Compatibility & Read-Only Live Preflight (`manifest.py`, `acceptance_harness.py`, `cli.py`):**
   - Updated `MinerManifest.resolve_from_mining_repo()` to pass `-KrigCoreClockMHz` / `--gpu-cclock` when `krig_core_clock_mhz > 0`.
   - Added `run_live_acceptance_preflight()` and `resource-coordinator preflight --check-live` to perform strictly read-only checks for external miner processes, `SingleInstanceLock` contention, LM Studio loaded models, and GPU VRAM headroom.
6. **Evidence Integrity (`acceptance_harness.py`):**
   - Initialized `mode="live"` reports with `verification_level = "pending_live_verification"` and promoted to `"live_hardware"` only after all live trials execute and pass without test overrides.

### 4.2 Remote `origin/main` Divergence Analysis (`109c7ad0..f98dcdb5`)
- Inspected `origin/main` (10 commits ahead of original base `109c7ad0` from `20261102-managed-monitor-ops`).
- `git diff --name-status 109c7ad0..origin/main` touches only `modules/llm_monitor/*`, `modules/agent_benchmark/*`, `modules/web_ui_tools/*`, `docs/agent/MANAGED_MONITOR_POLICY.md`, and `docs/plans/20261102-managed-monitor-ops/*`.
- **Zero overlapping files and zero merge conflicts** exist with `feature/miner-inference-coordination-20261102` (which exclusively modifies `modules/resource_coordinator/*`).
- No rebase was performed, preserving branch history as instructed.
