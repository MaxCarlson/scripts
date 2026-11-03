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

---

## 5. Final Acceptance Preparation & Deployment Readiness

### 5.1 Operational Corrections Implemented
1. **Correction A — Align Preflight and Real Execution:**
   - Implemented `AcceptanceHarness.from_config()` ensuring identical configuration is executed by runner as validated in preflight.
   - Added `validate_acceptance_config_equivalence()` enforcing identical executable, working directory, arguments, backend, and external adoption flags (`ConfigurationMismatchError`).
   - Extended host `SingleInstanceLock` ownership across the entire acceptance run, preventing competing coordinators from operating during live trials.
   - Added immediate pre-launch safety re-check in `run_all()` to abort before launch if an unmanaged external miner appears in the OS process table.
   - Added `lmstudio.inference_forwarded` dispatcher event emitted immediately prior to upstream HTTP forward in `gateway.py`, validating `stop_verified_monotonic <= upstream_dispatch_monotonic`.
2. **Correction B — Repeatable, Evidence-Preserving Acceptance Runner:**
   - Introduced collision-resistant run directories (`.live_acceptance_work/runs/<run_id>/`) with `manifest.json`, per-trial journals (`journal_tXX.json`), and `acceptance_report.json`.
   - Maintained deterministic `latest_run.json` pointer file.
   - Guaranteed evidence preservation on trial cancellation or interruption in `run_all()` `finally:`, recording `status = "INTERRUPTED"`.
   - Supported partial trial sets via `--trials` (e.g. `--trials T01` yielding `verification_level = "live_hardware_partial_stage"`).
3. **Correction C — Mining Launcher Compatibility Reconciliation:**
   - Implemented `launcher_declares_parameter()` scanning PowerShell script parameter block before `Set-StrictMode`.
   - Validated that target launcher declares `-KrigCoreClockMHz` before emitting preview flags; fails closed with explicit `ValueError` if an unsupported flag is requested.
   - Ensured default coordinator configuration requests zero clock/power flags, preserving host GPU state.

### 5.2 Verification Evidence
- **New Regression Suite:** `modules/resource_coordinator/tests/test_final_acceptance_readiness.py`: **9 passed in 3.5s**.
- **Full Resource Coordinator Suite:** **320 passed, 4 skipped**.
- **Full LLM Monitor Suite:** **253 passed, 2 skipped**.
- **Real Windows Disposable Helper:** `resource-coordinator accept -m disposable_helper` verified with **5/5 trials passed (`os_process_contract`)**.
- **Dry-run Merge Tree:** `git merge-tree --write-tree origin/main HEAD` confirmed clean zero-conflict merge tree (`9a1d0427`).

---

## 6. Mining-Activity Verification & 3-Contract Partitioning (T01 Investigation & Enhancement)

### 6.1 Investigation of Prior T01 Run (`20261102_233303_5a9bdae3`)
An investigation was conducted into the discrepancy between the prior T01 run reporting `PASS` while the operator observed no noticeable increase in GPU utilization.
- **Root Cause Identified:**
  1. In `_run_trial_1_single_request`, after `service.start()` verified `initial_info.state == ProcessState.RUNNING`, `discover_live_model(client)` was called (~200ms) and the inference request was immediately posted. The inference arrival triggered `StopProcessAction` ~295ms after launch (total process lifetime ~758ms).
  2. Following the 10.016s idle cooldown, post-restart KRig was verified in `RUNNING` state (~10ms) and execution immediately entered `finally:`, terminating the restarted process ~47ms after start.
  3. KRig requires 3–10 seconds to initialize its CUDA runtime, allocate device buffers, connect to the Stratum pool, and ramp GPU compute load from idle (~40 W) to full Pearl hashing (~350–550 W).
  4. `WindowsProcessBackend` redirected `stdout` and `stderr` to `subprocess.DEVNULL`, suppressing all miner diagnostic output and pool connection telemetry.
- **Historical Verdict Classification:** Run `20261102_233303_5a9bdae3` is officially reclassified as: **"Process coordination verified; actual mining activity not established."**

### 6.2 Implementation of Mining-Activity Verification
1. **Stdout/Stderr Logging (`config.py`, `core/processes.py`):**
   - Added `stdout_log_path: Optional[str] = None` to `ProcessConfig`, `WindowsProcessBackend`, and `CoordinatorConfig.from_dict()`.
   - Directed stdout/stderr to `trial_dir / "miner_stdout.log"` with clean handle lifecycle and automatic closing on process exit/termination.
2. **GPU Telemetry Sampler (`acceptance_harness.py`):**
   - Added `GpuActivitySampler` sampling GPU utilization, power draw, and VRAM at 1–2 Hz via `GpuMonitor`.
   - Captured pre-launch `gpu_idle_baseline` and evaluated sustained activity (elevated power or utilization across consecutive samples).
3. **Log Telemetry Parsing (`acceptance_harness.py`):**
   - Added `parse_miner_stdout_log()` parsing pool connection (`"Connected to"`, `"Subscribed"`) and reported hashrate (`"Speed: ... MH/s"`).
4. **Three-Contract Partitioning (`TrialEvidence`):**
   - **Contract A (`process_contract_verified`):** OS process launch, PID tracking, stop barrier, cooldown restart, and supervised cleanup.
   - **Contract B (`inference_arbitration_contract_verified`):** Stop barrier strictly before forward, zero miner activity during inference, 10.0s cooldown, and restart on idle.
   - **Contract C (`mining_activity_contract_verified`):** Actual sustained GPU hashing confirmed prior to inference request and after cooldown restart.
   - For `live` mode, `TrialEvidence.status` requires contracts A, B, and C to be True.
5. **Bounded Warm-up Verification (`_verify_mining_warmup`):**
   - Verified initial mining activity within a bounded window (`mining_warmup_timeout_seconds`, default 60s live) and allowed settling (`mining_settle_seconds = 3.0s` live) before dispatching inference.
   - Verified post-restart mining activity after the 10-second cooldown before trial completion.
   - Detects premature miner process termination immediately and fails fast.
   - Preserves guaranteed cleanup in `finally:` on all failure paths.

### 6.3 Process Generation Log Isolation, Phase-Isolated GPU Sampling, and Settling State Machine
To guarantee evidence integrity between initial launch and post-cooldown restart:
1. **Process-Generation Log Isolation (`core/processes.py`, `acceptance_harness.py`):**
   - `WindowsProcessBackend` increments generation count (`_generation`) and writes an explicit delimiter header on each start (`--- [COORDINATOR GENERATION {gen} PID {pid} STARTED AT {ts}] ---`).
   - `parse_miner_stdout_log` accepts `start_offset: int = 0`, reading only log bytes emitted after the process generation's launch offset. Old hashrate lines from prior generations are strictly ignored.
   - Strips ANSI color/escape sequences (`\x1b\[[0-?]*[ -/]*[@-~]`) and accurately distinguishes pool connection confirmations from command-line argument echoes (`--url stratum+ssl:...`).
2. **Phase-Isolated GPU Sampling (`acceptance_harness.py`):**
   - `GpuActivitySampler` maintains `PhaseGpuEvidence` isolated by phase (`initial` vs `restart`), storing generation-specific baselines, peak power, peak utilization, and sample histories.
   - Samples from the initial warm-up phase never leak into restart evaluation.
3. **Settling-Period Activity Revalidation State Machine (`acceptance_harness.py`):**
   - Implemented a 5-state state machine: `PROCESS_LAUNCHED` -> `ACTIVITY_DETECTED` -> `SUSTAINED_ACTIVITY_CONFIRMED` -> `SETTLING_IN_PROGRESS` -> `WARMUP_VERIFIED`.
   - Continuous verification during `mining_settle_seconds`: transient activity spikes that drop back to idle reset the settle timer, preventing false positives.
4. **Evidence Classification Taxonomy:**
   - Formalized evidence classifications: `hashing_verified`, `gpu_compute_activity_observed`, `miner_hashrate_reported`, `pool_connection_verified`, `process_running`, and `verification_inconclusive`.
   - Recorded structured evidence dictionaries in `trial.initial_generation` and `trial.restart_generation`.

### 6.4 Verification Evidence
- **Comprehensive Activity Verification Suite:** `modules/resource_coordinator/tests/test_mining_activity_verification.py`: **10 passed in 4.3s**.
- **Process Backend Logging Tests:** `modules/resource_coordinator/tests/test_processes.py`: **5 passed in 0.8s**.
- **Full Resource Coordinator Suite:** **337 passed, 4 skipped**.
- **Real Windows Disposable Helper:** `resource-coordinator accept -m disposable_helper` verified with **5/5 trials passed (`os_process_contract`)**.
- **Read-Only Live Preflight:** `resource-coordinator preflight --check-live`: **READY** (2036 MiB free VRAM, `qwen38_23GB` loaded).

### 6.5 Supervised T01 Live-Hardware Rerun Verification
Following explicit operator authorization, supervised T01 rerun `20261103_004050_cac310be` was executed on the live RTX 5090 host:
- **Generation 1 (Initial Launch):** PID `61272`, connected to `stratum+ssl://prl-us.kryptex.network:8048`, received jobs `a55d8ce4_2097152` and `d1569e1f_2097152`. Power increased from baseline `35.44 W` to `75.42 W` (`11.0%` util) with `3.0s` continuous settling verified.
- **Inference Arbitration:** Stop barrier verified at monotonic `286248.171` before upstream dispatch at `286248.515` (gap `0.344s`). Miner stayed `STOPPED` throughout inference. LM Studio responded with HTTP `200` (`6797 ms` duration).
- **Idle Cooldown:** Cooldown elapsed `10.032s` (target `10.0s`).
- **Generation 2 (Post-Cooldown Restart):** Distinct PID `60904`, generation 2 log offset `1212`, connected to pool, received job `26e98a41_2097152`. GPU power surged to **603.6 W** and utilization reached **100.0%** across 39 GPU samples, with `3.015s` continuous settling verified.
- **Supervised Cleanup:** Post-trial termination verified (`cleanup_verified_stopped: true`, `descendants_verified_stopped: true`), zero orphan processes, host lock cleanly released.
- **Verdict:** Automated runner verdict `PASS` (`verification_level = "live_hardware_partial_stage"`). Both process coordination and physical GPU compute load independently confirmed. Ready for operator authorization of trials T02–T04.
