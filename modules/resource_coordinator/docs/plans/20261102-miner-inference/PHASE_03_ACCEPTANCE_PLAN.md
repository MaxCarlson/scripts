# Phase 03 — Supervised Hardware Acceptance Plan & Operator Checklist

**Status:** Hardware Acceptance Harness & Read-Only Preflight Verified; Awaiting Operator Execution Window  
**Primary Module:** `modules/resource_coordinator`  
**Target Topology:**
```text
Inference Client (OpenCode / Benchmark / Acceptance Runner)
    │
    ▼
[Optional: LLM Monitor Port 8789]
    │
    ▼
Resource Coordinator Port 1235
    │ (Durable Journal + SingleInstanceLock + Stop-Before-Forward Barrier)
    ▼
LM Studio Port 1234 (RTX 5090 / Loaded Model: qwen38_23GB)
```

---

## 1. Non-Negotiable Safety & Authorization Boundaries

1. **No Adoption or Termination of External Miners:**
   - Any `krig-miner.exe` or `SRBMiner-MULTI.exe` started outside the coordinator (such as an interactive `start-prl.ps1` session or `runmux` window) is **external/foreign**.
   - All acceptance configurations enforce `adopt_external: false`, `allow_external_stop: false`, and `allow_external_restart: false`.
   - Read-only preflight (`run_live_acceptance_preflight`) scans the OS process table (`psutil.process_iter`) and **blocks** live acceptance if any external miner process is running. The operator must manually stop any external miner (`Ctrl+C` in its console) before starting supervised acceptance.

2. **No Automatic GPU Clock or Power Limit Mutations:**
   - In `C:\Users\mcarls\src\Mining\start-prl.ps1`, passing `-PowerLimitWatts 550` triggers UAC elevation (`-Verb RunAs`) and runs `nvidia-smi --power-limit=550`.
   - The coordinator **never** invokes UAC elevation or `nvidia-smi -pl`. Instead, it launches `C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\krig-miner.exe` directly as a non-elevated child process in its own Windows console process group (`new_console: false`, `CREATE_NEW_PROCESS_GROUP`).
   - If the operator desires a hardware power cap (e.g., 550 W), the operator sets that cap independently at the OS/driver level outside the coordinator.

3. **Zero Disruption to Active Host Services:**
   - LM Studio (`127.0.0.1:1234`), LLM Monitor (`127.0.0.1:8789`, PID `58828`), and active OpenCode workers (`47108`, `63836`) are never restarted, reconfigured, or interrupted by preflight or offline/disposable tests.

---

## 2. Operational Compatibility Snapshot (Verified Read-Only)

| Component | Verified Host Configuration | Compatibility Notes |
|---|---|---|
| **Mining Launcher & Binary** | `C:\Users\mcarls\src\Mining\start-prl.ps1`<br>Binary: `C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\krig-miner.exe`<br>Args: `--coin pearl --url stratum+ssl://prl-us.kryptex.network:8048 --user krxXPVG8JN/Xeres` | Resolved via `MinerManifest.resolve_from_mining_repo()` (supports both `start-prl.ps1 -Preview` and static resolution, including optional `-KrigCoreClockMHz` / `--gpu-cclock`). Credentials redacted in logs via `redact_miner_args()`. |
| **LM Studio Upstream** | `http://127.0.0.1:1234`<br>Loaded model (`/api/v0/models`): `qwen38_23GB` (`state: "loaded"`, `type: "llm"`, `loaded_context_length: 98304`) | `discover_live_model()` queries `GET /api/v0/models` first and selects the resident `state == "loaded"` LLM/VLM (`qwen38_23GB`), refusing to trigger an unintended model auto-load. Falls back to `GET /v1/models` only if `/api/v0/models` returns 404. |
| **GPU & VRAM Headroom** | NVIDIA GeForce RTX 5090 (`32,607 MiB` total)<br>Used with resident `qwen38_23GB` (96k ctx): `30,690 MiB` (`1,498 MiB` free) | Pearl (`pearlhash`) on `krig-miner.exe` is compute-bound and coexists within the `1,498 MiB` free VRAM headroom alongside `qwen38_23GB`. `run_live_acceptance_preflight()` verifies free VRAM against `--min-free-vram-mb` (default `1024 MiB`). |
| **External Miner Check** | Detected active external `krig-miner.exe` (PID `69988`, parent PID `15808`) running at ~550 W during read-only inspection | Preflight accurately flags PID `69988` as a blocking external miner without touching it. Operator must stop PID `69988` before executing live coordinator-owned trials. |

---

## 3. Acceptance Harness Architecture & Evidence Integrity

Implemented in [`modules/resource_coordinator/resource_coordinator/acceptance_harness.py`](file:///C:/Users/mcarls/src/scripts\.worktrees/miner-inference-coordination-20261102/modules/resource_coordinator/resource_coordinator/acceptance_harness.py):

### Guaranteed Cleanup & Failure Handling
- Every trial (`T01`–`T05`) executes `_cleanup_trial_harness()` inside a `finally:` block, regardless of assertion failures, upstream HTTP errors, timeouts, or task cancellation.
- Cleanup stops the `CoordinatorService`, verifies `backend.status().state == ProcessState.STOPPED`, and on Windows (`WindowsProcessBackend`) inspects all recorded `(pid, create_time)` identities via `psutil` to ensure both the owned process and any recursive child/descendant processes have exited.
- **Fail-Closed Rule:** If process or descendant termination cannot be verified during cleanup, `t.metrics["cleanup_verified_stopped"]` is recorded as `False` and `t.status` is forced to `"FAIL"` (never `"PASS"`).

### Durable Safety per Trial
- Each trial initializes an isolated durable journal (`journal_<trial_id>.json`) via `StateCodec.initialize()` and acquires an exclusive `SingleInstanceLock` (`coordinator.lock`), preventing concurrent coordinator instances from operating simultaneously.

### Strict Separation of Verification Levels
| Mode | Process Backend | Upstream | `verification_level` | Trials Executed |
|---|---|---|---|---|
| `simulated` | `FakeProcessBackend` | ASGI Mock | `unit_simulation` | `T01`, `T02`, `T03`, `T04`, `T05` |
| `disposable_helper` | Real Windows `cscript.exe` (`windows_miner_helper.vbs`) | ASGI Mock | `os_process_contract` | `T01`, `T02`, `T03`, `T04`, `T05` |
| `live` (before run) | `WindowsProcessBackend` (`krig-miner.exe`) | Live LM Studio | `pending_live_verification` | None yet |
| `live` (with test overrides) | `WindowsProcessBackend` | Test Override | `live_contract_rehearsal` | `T01`, `T02`, `T03`, `T04` (`T05` skipped as mock-only) |
| `live` (after all live trials pass) | `WindowsProcessBackend` (`krig-miner.exe`) | Live LM Studio (`:1234`) | `live_hardware` | `T01`, `T02`, `T03`, `T04` (full 10.0s cooldown) |

### Three-Contract Acceptance Partitioning
To guarantee both process safety and physical compute correctness, trials in `live` mode evaluate three distinct contracts:
- **Contract A (`process_contract_verified`):** OS process launch, PID tracking, stop barrier, cooldown restart, and verified cleanup.
- **Contract B (`inference_arbitration_contract_verified`):** Stop barrier strictly before forward, zero miner activity during inference, full 10.0s cooldown, and restart on idle.
- **Contract C (`mining_activity_contract_verified`):** Actual sustained GPU hashing confirmed prior to inference request and after cooldown restart.
A live trial passes only when Contracts A, B, and C are all verified.

### Bounded Warm-up Verification & Settling State Machine (`_verify_mining_warmup`)
To allow the miner to initialize CUDA, connect to the Stratum pool, and ramp GPU compute load before the inference request arrives:
- Captures pre-launch baseline GPU power and utilization (`gpu_idle_baseline`).
- Diverts miner output to `trial_dir / "miner_stdout.log"` via `stdout_log_path`.
- Implements **process-generation log isolation**: writes explicit generation delimiter headers and tracks `last_launch_log_offset`; `parse_miner_stdout_log` reads from `start_offset`, preventing restarted processes from inheriting historical hashrate evidence.
- Strips ANSI codes, verifies genuine Stratum pool connection confirmations (`connected: stratum+ssl://...`) while rejecting CLI argument echoes, extracts Stratum jobs, and parses reported hashrate.
- Isolates GPU samples by phase (`PhaseGpuEvidence`: `initial` vs `restart`), ensuring initial warm-up samples never leak into restart evaluations.
- Evaluates activity through an explicit 5-state state machine:
  `PROCESS_LAUNCHED` -> `ACTIVITY_DETECTED` -> `SUSTAINED_ACTIVITY_CONFIRMED` -> `SETTLING_IN_PROGRESS` -> `WARMUP_VERIFIED`.
- Verifies sustained hashing via dual corroborating signals:
  1. Elevated GPU power draw (`>= baseline + 35W`) or load (`>= baseline + 15%`) across consecutive samples.
  2. Miner stdout log hashrate (`Speed: ... MH/s` / `Total: ... TH/s`).
- Enforces continuously sustained activity throughout `mining_settle_seconds` (`3.0s` live); transient spikes that drop back to idle reset the settle timer.
- Repeats bounded warm-up verification after the 10.0-second cooldown restart before test completion.
- Fails fast immediately if the miner process terminates prematurely during warm-up.

### Recorded Per-Trial Telemetry (`TrialEvidence`)
Every trial records:
- `model_id` (discovered via read-only `/api/v0/models` or `/v1/models`)
- `initial_pid` and `initial_create_time`
- `process_contract_verified`, `inference_arbitration_contract_verified`, `mining_activity_contract_verified`
- `initial_generation` and `restart_generation` structured evidence dictionaries:
  - `generation`, `phase`, `pid`, `create_time`, `launch_monotonic`
  - `verified`, `settling_verified`
  - `evidence_classification` (`hashing_verified`, `gpu_compute_activity_observed`, `miner_hashrate_reported`, `pool_connection_verified`, `process_running`, `verification_inconclusive`)
  - `verification_method`, `peak_power_w`, `peak_utilization_pct`, `gpu_samples_count`
  - `log_start_offset`, `log_end_offset`, `pool_connected`, `connected_pool_url`, `pool_job_received`, `hashrate`, `hashrate_ths`
  - `warmup_duration_seconds`, `settling_duration_seconds`
- `initial_miner_uptime_before_inference_seconds` and `initial_mining_activity_verified`
- `initial_hashrate` and `initial_pool_connected`
- `restart_mining_activity_verified` and `restart_time_to_hashing_seconds`
- `gpu_idle_baseline`, `peak_gpu_power_w`, and `peak_gpu_utilization_pct`
- `mining_verification_method` (`gpu_telemetry+miner_stdout`, `gpu_telemetry`, `miner_stdout`, `simulated`)
- `stopped_before_forward_verified` (boolean proven by monotonic timestamps)
- `observed_exit_during_inference` (boolean confirming miner stayed `STOPPED` throughout forwarding)
- `inference_result` (HTTP status code and SSE `[DONE]` observation)
- `cooldown_target_seconds` and `cooldown_elapsed_seconds` (monotonic delta from `resource.cooldown_started` to `process.started`)
- `restarted_pid` and `restarted_create_time`
- `cleanup_verified_stopped` and `descendants_verified_stopped`
- `journal_path` and `lock_path`

---

## 4. Operator-Controlled 6-Stage Live Acceptance Procedure

The acceptance procedure is partitioned into 6 operator-controlled stages to ensure complete safety and verification at every boundary:

### Stage 1 — Read-Only Preflight Verification
Verify that the configuration, lock availability, LM Studio model, and GPU VRAM headroom meet all acceptance requirements without touching running processes:
```powershell
$env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
python -m resource_coordinator.cli preflight -c modules/resource_coordinator/config.live-local.yaml --check-live
```
**Acceptance Checkpoint:**
- Preflight reports `Loaded Model: qwen38_23GB` (source `/api/v0/models`, context `98304`).
- Free VRAM >= 1024 MiB (e.g., ~1498–2687 MiB free).
- If external miner PID `69988` is active, it is safely identified in `BLOCKING:` without being interrupted.

### Stage 2 — Operator-Controlled Preparation
The operator manually terminates any external miner session and verifies preflight transitions to `READY`:
1. Press `Ctrl+C` in the external `start-prl.ps1` / `krig-miner.exe` console (PID `69988`).
2. Verify process exit:
   ```powershell
   Get-Process -Name "krig-miner" -ErrorAction SilentlyContinue
   ```
3. Re-run preflight:
   ```powershell
   python -m resource_coordinator.cli preflight -c modules/resource_coordinator/config.live-local.yaml --check-live
   ```
**Acceptance Checkpoint:**
- Preflight reports `Live Acceptance Preflight: READY`.
- Zero blocking reasons reported. Exit code `0`.

### Stage 3 — Supervised Hardware Trial (Single Request Cycle)
> [!NOTE] Historical Run Status
> The earlier initial run `20261102_233303_5a9bdae3` verified process creation, stop barrier, cooldown timing, and restart, but stopped the miner before CUDA initialization and hashing began (no GPU compute load). It is classified as: **"Process coordination verified; actual mining activity not established."**
> With the enhanced harness verifying Contracts A, B, and C, T01 is ready for a supervised rerun confirming full physical hashing.

Execute the single-request trial (`T01`) with warm-up verification:
```powershell
python -m resource_coordinator.cli accept -c modules/resource_coordinator/config.live-local.yaml -m live --allow-live-lmstudio --allow-real-miner --trials T01 -w modules/resource_coordinator/.live_acceptance_work
```
**Acceptance Checkpoint:**
- Initial miner launches and warms up until sustained hashing / elevated GPU load is verified.
- `T01: Single Request Stop Before Forward and Cooldown` completes with `[PASS]`.
- All three contracts verified: `process_contract_verified: true`, `inference_arbitration_contract_verified: true`, `mining_activity_contract_verified: true`.
- Partial stage verification level recorded: `"verification_level": "live_hardware_partial_stage"`.
- Collision-resistant directory created under `.live_acceptance_work/runs/<run_id>/` with `miner_stdout.log` and GPU samples.

### Stage 4 — Evidence Review
Inspect the generated trial evidence before authorizing multi-request or streaming trials:
1. Read the latest run summary:
   ```powershell
   Get-Content modules/resource_coordinator/.live_acceptance_work/latest_run.json
   ```
2. Verify in `.live_acceptance_work/runs/<run_id>/acceptance_report.json`:
   - `initial_pid`: coordinator-owned `krig-miner.exe` PID recorded.
   - `stopped_before_forward_verified`: `true` (`stop_verified_monotonic <= upstream_dispatch_monotonic`).
   - `observed_exit_during_inference`: `true` (miner remained stopped during inference).
   - `inference_result`: status code `200` from LM Studio.
   - `cooldown_elapsed_seconds`: >= `9.85` seconds.
   - `restarted_pid`: distinct PID recorded on post-cooldown restart.
   - `cleanup_verified_stopped`: `true`.

### Stage 5 — Remaining Acceptance Trials (Concurrency & Streaming)
Execute the remaining trials (`T02`, `T03`, `T04`) covering cooldown cancellation, overlapping concurrent inference, and SSE stream termination:
```powershell
python -m resource_coordinator.cli accept -c modules/resource_coordinator/config.live-local.yaml -m live --allow-live-lmstudio --allow-real-miner --trials T02 T03 T04 -w modules/resource_coordinator/.live_acceptance_work
```
**Acceptance Checkpoint:**
- All three trials pass (`T02: PASS`, `T03: PASS`, `T04: PASS`).
- Cooldown debounce cancels restart immediately on incoming inference.
- Concurrent overlapping requests share the inference lease without restarting miner between requests.
- Streaming SSE inference maintains stop barrier until `[DONE]` token is emitted.
- All coordinator-owned processes are verified terminated during `finally` cleanup.

### Stage 6 — Deployment Decision & Client Migration
1. Review combined trial artifacts across all executed runs.
2. Confirm zero orphan `krig-miner.exe` processes:
   ```powershell
   python -m resource_coordinator.cli diagnose -c modules/resource_coordinator/config.live-local.yaml
   ```
3. When ready for production routing, follow [Section 5 of RUNBOOK.md](file:///C:/Users/mcarls/src/scripts/.worktrees/miner-inference-coordination-20261102/modules/resource_coordinator/docs/plans/20261102-miner-inference/RUNBOOK.md#5-client-migration--rollout-guide) to migrate client inference traffic to `http://127.0.0.1:1235`.

---

## 5. Emergency Recovery & Rollback Procedure

If any unexpected behavior occurs during a live session:
1. **Immediate Interrupt (`Ctrl+C`):** Triggers the `finally` cleanup barrier in `AcceptanceHarness` (or `CoordinatorService.stop()`), immediately latching restart inhibition, terminating the coordinator-owned `krig-miner.exe` process tree, and releasing `coordinator.lock`.
2. **Emergency Abort (When Running `serve`):**
   ```powershell
   $env:RESOURCE_COORDINATOR_OPERATOR_TOKEN = "<your-token>"
   python -m resource_coordinator.cli abort -u http://127.0.0.1:1235 -r "Operator manual abort"
   ```
   Immediately closes traffic admission and latches `RestartInhibition` across all tracked resources.
3. **Audited Operator Recovery (Clearing a Latched Hold After Confirming LM Studio Idle):**
   ```powershell
   $env:RESOURCE_COORDINATOR_RECOVERY_TOKEN = "<your-token>"
   python -m resource_coordinator.cli recover -u http://127.0.0.1:1235 -r gpu.inference --force -n "Verified LM Studio idle and GPU clear"
   ```
   Atomically transitions unresolved journal records to `operator_resolved` before clearing the in-memory hold and starting the 10-second idle cooldown.
4. **Client Rollback:** Because production clients (`LLM Monitor :8789` -> `LM Studio :1234`) have not been cut over, stopping the coordinator on `:1235` has zero impact on existing host traffic.
