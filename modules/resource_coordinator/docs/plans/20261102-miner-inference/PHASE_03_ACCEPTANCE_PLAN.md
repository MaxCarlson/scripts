# Phase 03 — Supervised Real Acceptance Plan & Operational Boundaries

**Status:** Plan & Harness Ready; live execution against unmanaged host miners requires explicit operator authorization.  
**Primary Module:** `modules/resource_coordinator`  
**Target Topology:**
```
Inference Client (OpenCode / Benchmark)
    │
    ▼
[Optional: LLM Monitor Port 8789]
    │
    ▼
Resource Coordinator Port 1235
    │ (Lease arbitration + Miner stop verification)
    ▼
LM Studio Port 1234 (RTX 5090 / qwen38-27b-q4km)
```

---

## 1. Safety Boundaries & Operations Requiring Explicit Authorization

The following actions MUST NOT be taken automatically without explicit operator consent:

1. **Adopting or Terminating Foreign Miners:**
   - Any currently running `krig.exe` or `SRBMiner-MULTI.exe` started externally (e.g. from an interactive PowerShell terminal or Task Scheduler) is **foreign**.
   - The coordinator will refuse to kill or adopt foreign processes (`adopt_external: false` by default).
   - Only processes launched directly by the coordinator as a child process group with tracked PID and exact `create_time` are managed.

2. **GPU Overclocking and Power Limit Mutations:**
   - The RTX 5090 host is configured with high-performance power limits (up to 600W).
   - The coordinator does **not** alter GPU power limits (`nvidia-smi -pl`) during request cycles.
   - Power policy must remain decoupled from request-driven stop/start cycles.

3. **In-Flight Service Interruption:**
   - OpenCode workers (e.g. PIDs 47108, 63836) and active benchmarks must not be interrupted.
   - Test runs should use isolated clients or dedicated request scopes.

---

## 2. Automated Acceptance Harness

The automated test runner is implemented in:
[`modules/resource_coordinator/resource_coordinator/acceptance_harness.py`](file:///C:/Users/mcarls/src/scripts/.worktrees/miner-inference-coordination-20261102/modules/resource_coordinator/resource_coordinator/acceptance_harness.py)

### Supported Modes:

1. **`simulated` (Default & Offline):**
   - Uses `FakeProcessBackend` and in-memory mock upstream LM Studio.
   - Fully automated and safe for CI and pre-commit checks.
   - Validates all 5 lifecycle trials with monotonic clock accuracy.

2. **`disposable_helper`:**
   - Spawns a disposable Windows helper (`cscript.exe //NoLogo modules/resource_coordinator/resource_coordinator/adapters/miners/windows_miner_helper.vbs`) instead of real mining hardware.
   - Proves Windows console process group signaling (`GenerateConsoleCtrlEvent`), child process tree cleanup, and fail-closed stop barriers without touching real GPUs.

3. **`live` (Requires Operator Approval):**
   - Requires `--allow-live-lmstudio` and `--allow-real-miner` flags.
   - Points upstream to `http://127.0.0.1:1234` and launches KRig via `MinerManifest.to_process_config()`.

---

## 3. Five Acceptance Trials

| Trial ID | Scenario | Verification Gate |
|---|---|---|
| **T01** | Single Request | 1. Request arrived.<br>2. Miner stop initiated.<br>3. Miner **verified stopped before** forward.<br>4. Upstream responds.<br>5. Exactly 10.0s idle cooldown elapsed.<br>6. Miner restarts. |
| **T02** | Cooldown Debounce | Request arriving at T+5s or T+9s during 10s cooldown cancels restart intent immediately; no premature start. |
| **T03** | Concurrent Overlap | Two requests running concurrently hold miner stopped; cooldown begins only after the **final** verified request completes. |
| **T04** | Streaming SSE | SSE stream terminates cleanly on `data: [DONE]`; chunk boundaries do not trigger premature release. |
| **T05** | Error / Abrupt Disconnect | Truncated stream or upstream 500 error triggers `RestartInhibition` (`gpu.inference`); miner remains stopped until operator recovery. |

---

## 4. Execution Command

To run the offline simulated acceptance suite and produce an evidence file:
```powershell
$env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
pytest modules/resource_coordinator/tests/test_phase3_acceptance_harness.py -v
```

Output evidence is written to:
`acceptance_evidence_<timestamp>.json`
Containing high-resolution monotonic timestamps, metrics, process IDs, and trial status.

---

## 5. Rollback and Recovery

If an issue occurs during testing:
1. **Emergency Abort:** Call authenticated endpoint `POST /coordinator/abort` with operator token. Admission is immediately closed and restarts latched.
2. **Clear Holds:** Call `POST /coordinator/recover?resource=gpu.inference` with explicit operator reason.
3. **Service Shutdown:** Send SIGINT (CTRL+C) or call `service.stop()`. The single-instance lock is freed, and the process exits cleanly.
