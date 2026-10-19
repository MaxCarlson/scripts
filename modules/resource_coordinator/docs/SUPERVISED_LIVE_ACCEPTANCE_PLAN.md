# Supervised Live Acceptance — Preparation & Safety Gates

**Document Status:** Stage 4 / Pre-Live Readiness Checklist  
**Current Decision:** **NO-GO for live operation** pending Codex Sol Medium final authorization.  
**Reference Design:** [Phase D Integration Design](PHASE_D_INTEGRATION_DESIGN.md)  
**Emergency Procedures:** [Emergency Abort Procedure](EMERGENCY_ABORT_PROCEDURE.md)

---

## 1. Readiness Status Summary

Phase D has completed the implementation and offline validation of all required coordinator-owned service lifecycle, centralized request admission, and emergency abort mechanisms. 186 offline tests pass cleanly.

| Safety Gate | Offline Implementation Status | Live Acceptance Requirement | Status |
| :--- | :--- | :--- | :--- |
| **Gate 1: Service Lifecycle** | `CoordinatorService` state machine (`CREATED` -> `INITIALIZING` -> `PREFLIGHT` -> `READY` -> `DRAINING` -> `STOPPED` / `FAILED` / `RECONCILIATION_REQUIRED`) implemented and tested. | Verified offline in 16 integration scenarios. | **READY (OFFLINE)** |
| **Gate 2: Centralized Admission** | `AdmissionController` and `OperationClassifier` fail closed (503 on unready/draining, 501 on unknown mutating, 503 on uncoordinated model load). | Verified offline; blocks all premature or unauthorized traffic. | **READY (OFFLINE)** |
| **Gate 3: Process Ownership** | `ProcessSupervisor` with exact PID, creation time, and executable matching. Standalone mutation disabled. | Coordinator-owned launch (`--start-miner`, `--stop-miner-on-shutdown`). | **READY (OFFLINE)** |
| **Gate 4: Emergency Abort** | HTTP `POST /_coordinator/abort` and CLI `resource-coordinator abort`. Imposes permanent restart inhibition without blind kills. | Verified in Scenario 16 and unit tests. | **READY (OFFLINE)** |
| **Gate 5: Private Config & Env** | Placeholder template sanitized. Real paths, wallet args, and local process settings required. | Operator must create and review `config.private.yaml` locally. | **PENDING OPERATOR** |
| **Gate 6: Client & Model Isolation**| Admission controller rejects external mutating calls. | Operator must isolate port 1234/1235 traffic and preload Qwen model out-of-band. | **PENDING OPERATOR** |
| **Gate 7: Sol Medium Authorization**| Full offline evidence documented in `PHASE_D_INTEGRATION_HANDOFF.md`. | Explicit authorization by Codex Sol Medium required. | **PENDING SOL REVIEW** |

---

## 2. Mandatory Pre-Flight Operational Conditions

Before any live test can be scheduled, the human operator must verify the following physical and environment prerequisites:

### 1. Workload Isolation
- Ensure no automated benchmark scripts, OpenCode background workers, or scheduled tasks are sending traffic to port 1234 or port 1235.
- Ensure LM Studio is bound exclusively to `127.0.0.1:1234` (local loopback only).
- Confirm that no third-party mining watchdogs (e.g., Kryptex auto-relauncher, external cron, or scheduled tasks) are active on the host.

### 2. Model Residency
- Manually launch LM Studio out-of-band.
- Preload the designated Qwen model into VRAM.
- Confirm the model is resident and idle. Verify VRAM usage in `nvidia-smi` (~24–28 GB resident for Qwen 38B, leaving sufficient headroom for the miner's DAG allocation or idle baseline).
- **Note:** An idle loaded model does NOT prevent mining under coordinator policy.

### 3. Private Configuration File
- Create `config.private.yaml` using exact Windows paths:
  ```yaml
  version: "1.0"
  service:
    listen_host: "127.0.0.1"
    listen_port: 1235
    upstream_url: "http://127.0.0.1:1234"
  processes:
    krig:
      name: "krig"
      backend: "windows"
      executable: "C:\\path\\to\\krig-miner.exe"
      arguments:
        - "--coin"
        - "pearl"
        - "--url"
        - "stratum+ssl://your-pool.org:8048"
        - "--user"
        - "your_wallet/Worker1"
      working_directory: "C:\\path\\to"
      new_console: false
      allow_external_stop: false
      allow_external_restart: false
      adopt_external: false
      allow_force_termination: false
  policies:
    - name: "prioritize-local-inference"
      trigger_event: "lmstudio.inference_requested"
      target_process: "krig"
      resource: "gpu.inference"
      cooldown_seconds: 30.0
      stop_process: true
      restart_process: true
      only_if_stopped_by_coordinator: true
  ```
- Run preflight validation:
  ```powershell
  python -m resource_coordinator.cli preflight --config config.private.yaml
  ```
- Preflight MUST output `PASSED`.

---

## 3. Step-by-Step Supervised Test Procedure (Once Authorized)

When explicitly authorized by Codex Sol Medium, the supervised test will proceed through the following strict sequence with the operator monitoring telemetry throughout:

```text
Step 1: Start Coordinator Service (with --start-miner)
  │   - Coordinator validates preflight and reaches READY
  │   - Krig miner launches under coordinator ownership (recorded PID/create-time)
  │
Step 2: Submit Single Synchronous Non-Streaming Inference
  │   - POST /v1/chat/completions (model: qwen38, stream: false)
  │   - Verify claim registered, miner stopped, stop verified before forward
  │   - Request returns HTTP 200 with completed choices
  │
Step 3: Observe Post-Inference Idle Cooldown
  │   - Resource enters 30-second cooldown
  │   - Verify Krig remains STOPPED during the full cooldown window
  │   - When cooldown expires, verify Krig automatically restarts under coordinator ownership
  │
Step 4: Graceful Coordinator Shutdown
  │   - Send SIGINT (Ctrl+C) to coordinator console
  │   - Coordinator drains active leases, stops Krig safely, reaches STOPPED
  │
Step 5: Post-Test Forensic Review
      - Review journal logs, audit events, and GPU power/VRAM trace
```

---

## 4. Abort Criteria

The operator must trigger an **Emergency Abort** immediately if any of the following occur:
1. `nvidia-smi` shows simultaneous mining and inference GPU compute saturation (>95% power draw with unexpected VRAM thrashing).
2. Miner fails to stop within the 10.0-second configured timeout.
3. Upstream LM Studio returns an unexpected error or hangs without completing.
4. Krig relaunches unexpectedly before the 30-second cooldown has expired.
5. Coordinator process crashes or throws an unhandled exception.

*See [Emergency Abort Procedure](EMERGENCY_ABORT_PROCEDURE.md) for execution instructions.*
