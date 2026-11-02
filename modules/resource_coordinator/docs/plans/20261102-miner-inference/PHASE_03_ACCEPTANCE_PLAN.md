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

### Recorded Per-Trial Telemetry (`TrialEvidence.metrics`)
Every trial records:
- `model_id` (discovered via read-only `/api/v0/models` or `/v1/models`)
- `initial_pid` and `initial_create_time`
- `stopped_before_forward_verified` (boolean proven by monotonic timestamps)
- `observed_exit_during_inference` (boolean confirming miner stayed `STOPPED` throughout forwarding)
- `inference_result` (HTTP status code and SSE `[DONE]` observation)
- `cooldown_target_seconds` and `cooldown_elapsed_seconds` (monotonic delta from `resource.cooldown_started` to `process.started`)
- `restarted_pid` and `restarted_create_time`
- `cleanup_verified_stopped` and `descendants_verified_stopped`
- `journal_path` and `lock_path`

---

## 4. Operator-Ready Step-by-Step Live Acceptance Checklist

### Step 1 — Stop Any External Miner Session
If an external `krig-miner.exe` or `start-prl.ps1` session is running (such as PID `69988`), press `Ctrl+C` in its console window and confirm it has exited.

### Step 2 — Prepare Local Supervised Configuration
Copy [`config.supervised-template.yaml`](file:///C:/Users/mcarls/src/scripts/.worktrees/miner-inference-coordination-20261102/modules/resource_coordinator/config.supervised-template.yaml) to an untracked local file (e.g. `modules/resource_coordinator/config.live-local.yaml`) with:
- `executable`: `"C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6\\krig-miner.exe"`
- `working_directory`: `"C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6"`
- `arguments`: `["--coin", "pearl", "--url", "stratum+ssl://prl-us.kryptex.network:8048", "--user", "krxXPVG8JN/Xeres", "--devices", "0", "--no-tui", "--gpu-no-reset-oc"]`
- `allow_force_termination`: `true` (recommended fallback if console `CTRL_BREAK_EVENT` times out after `stop_timeout_seconds: 10.0`)

### Step 3 — Run Read-Only Live Acceptance Preflight
From `C:\Users\mcarls\src\scripts\.worktrees\miner-inference-coordination-20261102`:
```powershell
$env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
python -m resource_coordinator.cli preflight -c modules/resource_coordinator/config.live-local.yaml --check-live
```
**Expected Output:**
- `Live Acceptance Preflight: READY`
- `Loaded Model: qwen38_23GB (source: /api/v0/models, context: 98304)`
- `GPU VRAM Free: ~1498 MiB free / 32607 MiB total (min required: 1024 MiB)`
- Exit code `0` (zero `BLOCKING:` lines).

### Step 4 — Execute Disposable Windows Helper Rehearsal (Optional Pre-Check)
Verify real Windows process-group stop/cooldown/restart and fault-injection cleanup using `cscript.exe` (no GPU or miner touched):
```powershell
$env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
pytest modules/resource_coordinator/tests/test_supervised_acceptance_readiness.py -v
```

### Step 5 — Execute Supervised Live Acceptance Sequence
When authorized to launch `krig-miner.exe` under coordinator ownership:
```powershell
$env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
python -c "
import asyncio
from pathlib import Path
from resource_coordinator.acceptance_harness import AcceptanceHarness
from resource_coordinator.adapters.miners.manifest import MinerManifest

manifest = MinerManifest.resolve_from_mining_repo(r'C:\Users\mcarls\src\Mining', miner_type='krig')
proc_cfg = manifest.to_process_config(name='krig_miner', stop_timeout_seconds=10.0, allow_force_termination=True)
harness = AcceptanceHarness(
    mode='live',
    cooldown_seconds=10.0,
    allow_live_lmstudio=True,
    allow_real_miner=True,
    lmstudio_url='http://127.0.0.1:1234',
    miner_process_config=proc_cfg,
    work_dir=Path('modules/resource_coordinator/.live_acceptance_work'),
)
report = asyncio.run(harness.run_all(output_file='modules/resource_coordinator/acceptance_evidence_live.json'))
print(report.summary)
"
```

### Step 6 — Inspect Evidence & Verify Post-Run Clean State
1. Open `modules/resource_coordinator/acceptance_evidence_live.json` and verify:
   - `"verification_level": "live_hardware"`
   - `"all_passed": true` (`"passed": 4, "failed": 0, "mock_only_trials_skipped": 1`)
   - Every trial (`T01`–`T04`) shows `"stopped_before_forward_verified": true`, `"observed_exit_during_inference": true`, `"cooldown_elapsed_seconds" >= 9.85`, and `"cleanup_verified_stopped": true`.
2. Run read-only diagnostics to confirm no leftover `krig-miner.exe` process remains running after harness exit:
   ```powershell
   python -m resource_coordinator.cli diagnose -c modules/resource_coordinator/config.live-local.yaml
   ```

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
