# Status Ledger: Miner / Local LLM Coordination

**Plan ID:** `miner-inference-coordination-20261102`  
**Current Phase:** Final Acceptance Preparation & Deployment Readiness Complete; Supervised Live Workflow Ready  
**Timestamp:** 2026-11-02T15:10:00-08:00  
**Host Platform:** Windows (win32, Python 3.12.10, PowerShell 7.5 / pwsh)  
**Primary Repository:** `C:\Users\mcarls\src\scripts`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\miner-inference-coordination-20261102`  
**Branch:** `feature/miner-inference-coordination-20261102` (branched from `109c7ad0edfb44b18e19505abf1def4ea58fac77`; zero file overlap with `origin/main` at `f98dcdb5`)  
**Companion Repository:** `C:\Users\mcarls\src\Mining` (branch `master` at `9c36ed042ec68fba956846917ede2d04678c5230`; working copy preserved untouched)  

---

## 1. Runtime and Process Discovery Inventory

| Resource / Process | Observed State | PID / Port / Details | Notes / Invariants |
|---|---|---|---|
| **LM Studio** | Active / Running | Port `1234` (Listen) | Loaded model (`/api/v0/models`): `qwen38_23GB` (`state: "loaded"`, `loaded_context_length: 98304`). Read-only discovery verified. |
| **LLM Monitor Web** | Active / Running | PID `58828` on Port `8789` | Command: `-m llm_monitor web -p 8789 -e http://127.0.0.1:1234 --gateway --gateway-upstream http://127.0.0.1:1234 -R content -n -d .../qualification.sqlite3`. Must NOT be interrupted. |
| **OpenCode Workers** | Active | PIDs `47108`, `63836` | Local coding worker processes active. Must NOT be disturbed. |
| **External Miner (`krig-miner.exe`)** | Active (External) | PID `69988` (Parent `15808`) | Elevated external `krig-miner.exe` session currently running on host. Read-only preflight detects PID `69988` and blocks starting a second miner until operator stops PID `69988`. |
| **Mining Scheduled Tasks** | None | None | No scheduled tasks for mining detected. |
| **Mining Windows Services** | None | None | No Windows services for mining detected. |
| **NVIDIA GPU** | Operational | GeForce RTX 5090 | 550W current power limit (~549.8W draw while external PID `69988` mines Pearl), `30,690 MiB` used / `1,498 MiB` free / `32,607 MiB` total VRAM. |
| **Resource Coordinator Service**| Inactive on host | Port `1235` (Free) | No host-wide coordinator running. Ephemeral test ports used for testing. |

---

## 2. Requirement-to-Existing-Code Gap Analysis

| Requirement | Existing Codebase State | Gap / Action Needed |
|---|---|---|
| **Stop before forward barrier** | Implemented in `LMStudioGateway._proxy_with_coordination` via `emit_blocking()` calling `StopProcessAction.execute()`. | Fully verified. Need integration tests proving strict stop before upstream dispatch with 10s cooldown. |
| **Atomic pending reservation & cooldown cancellation** | Implemented in `LeaseManager.reserve()`: increments pending and cancels cooldown before any await. | Verified in `leases.py`. Preserved without duplicating scheduler. |
| **10.0-second cooldown** | Config currently defaults to 60.0s in multiple places; legacy process `restart_cooldown_seconds` exists. | Standardize default policy cooldown to 10.0s for both inference and model loading. Verify cancellation on arrival. |
| **Two-proxy chaining (`Monitor -> Coordinator -> LM Studio`)** | LLM Monitor has `/v1/chat/completions` gateway forwarding to upstream. Coordinator reverse proxy forwards to LM Studio. | Add dedicated end-to-end chaining tests with simulated upstream and mock processes to verify headers, stream `[DONE]`, and lease lifetime. |
| **KRig/SRBMiner launch & ownership contract** | `start-prl.ps1` runs interactively or with elevation; `WindowsProcessBackend` uses `subprocess.Popen` with PID/create-time tracking and CTRL+BREAK. | Provide noninteractive, un-elevated miner launch configuration resolver/manifest preserving KRig flags (`--coin pearl`, `--url ...`, `--user ...`, `--gpu-cclock 2400`) without copying credentials into committed code. |
| **Durable state & crash safety** | `config.py` rejects `state_persistence_path` with `"State persistence is not implemented"`. `durable_state.py` lacks request journal, locks, or startup reconciliation. | Implement transactional journal for pre-forward intent, exclusive single-instance lock, crash recovery, and startup reconciliation (Phase 04). |
| **Unexpected miner exit recovery** | Currently, if process dies externally, `ProcessSupervisor` doesn't automatically restart unless `resource.idle` is fired. | Implement bounded exponential backoff supervision for unexpected miner exit during idle (Phase 04). |
| **Manual pause & operator override** | `ProcessSupervisor.set_manual_override()` and `LMStudioGateway.handle_coordinator_recover()` exist. | Ensure overrides are audited, reasoned, and persist across restarts. |

---

## 3. Baseline Verification Results

- `modules/resource_coordinator`:
  - 172 unit/policy/safety tests passed (`pytest test_leases.py test_actions.py test_admission.py test_gateway.py ...`).
  - Note: `phase_c_safety_review_test.py` had 2 tests mocking `asyncio.create_subprocess_exec` for GPU monitor, which was refactored in `main` to `asyncio.to_thread(nvidia_gpus)`. These will be aligned.
- `modules/llm_monitor`:
  - 253 passed, 2 skipped (`pytest modules/llm_monitor/tests`).
- Worktree clean and isolated on branch `feature/miner-inference-coordination-20261102`.

---

## 4. Current Phase & Next Action

- **Phase 0 (Discovery):** COMPLETE.
- **Phase 1 (Request Arbitration & Gateway Integration):** COMPLETE (Commit `e69457c0`).
  - Added deterministic tests for 10.0-second cooldown and boundary cancellation.
  - Added end-to-end test for `LLM Monitor gateway -> Resource Coordinator -> Mock LM Studio`.
  - Verified concurrent requests, streaming completion, and upstream failure handling.
  - Suite: 260 tests passed.
- **Phase 2 (Miner Process Integration):** COMPLETE (Commit `49e89a3f`).
  - Developed `MinerManifest` and `redact_miner_args` in `resource_coordinator.adapters.miners.manifest`.
  - Supported manifest resolution via `start-prl.ps1 -Preview` and known vendor executable paths without elevating wrappers.
  - Enhanced `WindowsProcessBackend` child process tree termination when force termination is allowed, while keeping safe verified failure when force termination is disallowed.
  - Tested process ownership, PID + creation-time verification, child tree termination, and disposable helper lifecycle.
  - Suite: 268 tests passed.
- **Phase 3 (Supervised Acceptance Preparation):** COMPLETE (Commit `8df99dd2`).
  - Implemented `AcceptanceHarness` executing 5 canonical trials (single request, debounce, concurrency, SSE stream, and error inhibition) with high-resolution monotonic timestamps.
  - Produced `PHASE_03_ACCEPTANCE_PLAN.md` documenting operational boundaries, authorization requirements, and rollback procedures.
- **Phase 4 (Unattended Reliability & Durable State):** COMPLETE (Commit `72ea1715`).
  - Implemented OS-visible `SingleInstanceLock` via `msvcrt` (Windows) and `fcntl` (POSIX) to prevent dual ownership and duplicate coordinators.
  - Added `RequestPhase` and `PersistedRequest` journal to `CoordinatorState` and `StateCodec`.
  - Wired atomic pre-forward intent commit (`POSSIBLY_FORWARDED`) and terminal verification into `LMStudioGateway`.
  - Wired crash-recovery startup reconciliation replaying unresolved requests into restart inhibitions in `CoordinatorService`.
  - Added bounded backoff restart and crash loop exhaustion watchdog for unexpected miner exits in `ProcessSupervisor`.
  - Suite: 278 passed across all resource coordinator tests.
- **Phase 5 (Client Adoption & Operational Runbook):** COMPLETE.
  - Produced operational runbook `RUNBOOK.md` covering port topologies, client migration paths, CLI commands, emergency abort, and rollback instructions.
  - Full regression suite verified.
- **Independent Review Remediation:** COMPLETE (Commit `d097f1c6`).
  - Addressed all findings from independent review across concurrency, persistence, and process supervision.
  - Hardened durable journal initialization (`StateCodec.initialize`), missing-state refusal on normal startup (`first_boot=True` requirement), and reservation cleanup on write failures.
  - Enabled persistent operator recovery (`resolve_unresolved_requests`) terminalizing crash records on disk.
  - Eliminated single-instance lock file unlinking race and descriptor leaks.
  - Fixed watchdog backoff cancellation so arrival of an inference request during sleep immediately aborts restart.
  - Wired continuous process supervision loop into `CoordinatorService`.
  - Aligned `MinerManifest` with committed `Mining\start-prl.ps1` and created `windows_miner_helper.vbs` for genuine OS-level disposable helper acceptance testing.
  - Corrected CLI keyword arguments and operational documentation.
  - Suite: 288 passed, 4 skipped across `modules/resource_coordinator`.
  - Authored comprehensive `ARGON_REVIEW_HANDOFF.md` package for independent adversarial review.
- **Independent Argon Adversarial Review & Hardening:** COMPLETE.
  - Conducted line-by-line adversarial source audit and added 10 deterministic regression tests in `modules/resource_coordinator/tests/test_argon_adversarial_review.py`.
  - **Finding A (`acceptance_harness.py`):** Rejected invalid modes (`ValueError`), enforced Windows requirement for `disposable_helper`, refused simulated `FakeProcessBackend` fallback in `live` mode, and verified all 5 trials against real Windows `cscript.exe` OS processes (`verification_level="os_process_contract"`).
  - **Finding B (`gateway.py`, `leases.py`, `durable_state.py`):** Executed durable journal resolution inside `LeaseManager.clear_inhibition(before_clear=...)` under `self._condition` before clearing in-memory inhibition or starting cooldown; introduced distinct `RequestPhase.OPERATOR_RESOLVED` (`operator_resolved`) preserving `previous_phase`.
  - **Finding C (`processes.py`, `service.py`, `leases.py`):** Serialized post-backoff watchdog restart through `lease_manager.run_if_idle(..., check_self_cooldown=True)`, enforced cooldown respect in watchdog supervision, removed lock-order inversion on crash-loop exhaustion, prevented spurious launch of never-started processes, and rolled back retry count when pre-empted by inference.
  - **Finding D (`durable_state.py`, `gateway.py`):** Removed silent `CoordinatorState()` recreation when an initialized journal disappears at runtime, and latched in-memory `RestartInhibition` if terminal journal persistence (`TERMINAL_VERIFIED` / `UNCERTAIN`) fails during request cleanup.
  - **Finding E (`durable_state.py`, `processes.py`, `service.py`, `config.py`):** Persisted `is_manual_override` in `PersistedProcess` across coordinator restarts and prevented `start_miner_on_ready` or normal shutdown `_freeze()` from clobbering operator pause state.
  - Verified full regression suites: **298 passed, 4 skipped** (`resource_coordinator`) and **253 passed, 2 skipped** (`llm_monitor`).
  - Recorded complete audit findings in `ARGON_REVIEW_RESULTS.md`.
- **Addendum — Supervised Hardware Acceptance Readiness:** COMPLETE.
  - Refactored `AcceptanceHarness` so every trial executes supervised cleanup in `finally:`, verifying miner and descendant process termination and forcing `status = "FAIL"` if stop verification fails.
  - Added read-only LM Studio model discovery (`discover_live_model` via `/api/v0/models` with fallback to `/v1/models`), separated mock-only `T05` from live trials (`T01`–`T04`), enforced 10.0s live cooldown, and recorded full PID/create_time/monotonic timing metrics.
  - Wired per-trial isolated durable journals (`StateCodec.initialize`) and `SingleInstanceLock` ownership into `AcceptanceHarness`.
  - Added read-only live acceptance preflight (`run_live_acceptance_preflight` and `resource-coordinator preflight --check-live`) checking external miners, lock contention, LM Studio loaded model, and GPU VRAM headroom.
  - Enforced evidence integrity (`verification_level = "pending_live_verification"` prior to execution; `"live_hardware"` only after un-mocked live execution and verification).
  - Added 10 fault-injection and readiness tests in `tests/test_supervised_acceptance_readiness.py`; verified full suites: **308 passed, 4 skipped** (`resource_coordinator`) and **253 passed, 2 skipped** (`llm_monitor`).
- **Final Acceptance Preparation & Deployment Readiness:** COMPLETE.
  - Resolved all remaining operational items:
    1. **Correction A (Align Preflight and Real Execution):** Implemented unified acceptance configuration shared by preflight and live runner (`AcceptanceHarness.from_config()`, `validate_acceptance_config_equivalence()`), shared host `SingleInstanceLock` covering entire acceptance run, immediate pre-launch safety re-check, and `lmstudio.inference_forwarded` event before `client.send` to differentiate actual dispatch from lease acquisition.
    2. **Correction B (Repeatable, Evidence-Preserving Acceptance):** Implemented collision-resistant per-run directory layout (`.live_acceptance_work/runs/<run_id>/`) with `manifest.json`, per-trial journals (`journal_tXX.json`), `acceptance_report.json`, and deterministic pointer `latest_run.json`. Guaranteed evidence preservation on interruption (`finally`), and supported partial trial sets via `--trials` (e.g. `--trials T01` yielding `verification_level = "live_hardware_partial_stage"`).
    3. **Correction C (Reconcile Mining Launcher Compatibility):** Implemented `launcher_declares_parameter` scanning script parameter block before `Set-StrictMode`; fail closed with clear `ValueError` if unsupported parameter is requested instead of silent fallback. Default coordinator configuration requests zero clock/power flags, preserving host GPU state.
  - Added CLI `accept` subcommand (`resource-coordinator accept`) and updated `.gitignore`.
  - Added 9 regression tests in `test_final_acceptance_readiness.py`.
  - Full test suites passed:
    - `resource_coordinator`: **320 passed, 4 skipped**.
    - `llm_monitor`: **253 passed, 2 skipped**.
  - Verified real Windows disposable helper acceptance (`resource-coordinator accept -m disposable_helper`): 5/5 trials passed (`os_process_contract`).
  - Read-only preflight tested (`resource-coordinator preflight --check-live`): correctly detects resident `qwen38_23GB` on LM Studio `:1234` and 32GB RTX 5090 VRAM.
  - Clean non-destructive merge assessment against `origin/main` (`f98dcdb5`): zero merge conflicts (`git merge-tree` clean).


