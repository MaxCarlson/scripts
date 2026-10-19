# Resource Coordinator — Emergency Abort Procedure

**Module:** `modules/resource_coordinator`  
**Target Platform:** Windows 11 / RTX 5090  
**Service Gateway:** `http://127.0.0.1:1235`  
**Upstream LM Studio:** `http://127.0.0.1:1234`  
**Managed Process:** Krig Miner (`krig-miner.exe`)

---

## 1. Overview & Immediate Safety Invariants

The Resource Coordinator emergency abort mechanism provides an immediate, non-destructive safety intervention designed to halt arbitration, close traffic admission, and prevent hazardous process restarts during live supervised testing.

### Invariants Guaranteed During Abort:
1. **Immediate Admission Closure:** All proxy traffic forwarding is halted immediately. In-flight and subsequent inference requests fail closed with HTTP 503 (`coordinator_not_ready` or `coordinator_draining`).
2. **Permanent Restart Inhibition:** Protective restart inhibitions are asserted across all managed resources (`gpu.inference`, `gpu.model_loading`). Cooldown timers are cancelled immediately; mining CANNOT resume automatically.
3. **Lifecycle State Transition:** The coordinator transitions to `RECONCILIATION_REQUIRED` or `STOPPED`.
4. **No Blind Process Termination:** The coordinator NEVER issues unconditional or ambiguous process kills against unverified PIDs or images named generically (e.g., `python.exe` or `krig-miner.exe`). If coordinator process ownership cannot be verified cryptographically/by creation time, processes are left for out-of-band operator reconciliation.

---

## 2. Emergency Trigger Methods

During a supervised integration test, the human operator can trigger an emergency abort via any of the following three paths:

### Method A: Coordinator CLI (Recommended)
From an administrative PowerShell terminal in the repository worktree:
```powershell
python -m resource_coordinator.cli abort --reason "Operator observed thermal anomaly or unexpected contention"
```
**Expected CLI Output:**
```text
Emergency abort acknowledged by coordinator:
  Status:        aborted
  Service State: reconciliation_required
  Reason:        Operator observed thermal anomaly or unexpected contention
  Inhibited:     gpu.inference, gpu.model_loading
```

### Method B: HTTP API Endpoint
If executing from an external monitor or shell:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:1235/_coordinator/abort" -Method Post -ContentType "application/json" -Body '{"reason":"Manual operator abort"}'
```
Or via curl:
```bash
curl -X POST http://127.0.0.1:1235/_coordinator/abort -H "Content-Type: application/json" -d '{"reason": "Manual operator abort"}'
```

### Method C: Keyboard Interrupt on Coordinator Console
If the coordinator is running in the foreground console (`serve`):
- Press `Ctrl + C` once.
- The coordinator enters `DRAINING` state with a bounded drain timeout.
- To force immediate non-graceful termination, press `Ctrl + C` a second time.

---

## 3. Post-Abort Operator Reconciliation Checklist

Once an emergency abort has been triggered, the operator must execute the following manual reconciliation steps before any system recovery:

```text
[ Emergency Abort Triggered ]
             │
             ▼
1. Verify Gateway Rejection (HTTP 503 for all proxy requests)
             │
             ▼
2. Verify Miner Process State Out-of-Band (Task Manager / Process Explorer)
             │
             ▼
3. Verify Upstream LM Studio State Out-of-Band (Idle / Active Model Inspection)
             │
             ▼
4. Determine Root Cause of Anomaly
             │
             ▼
5. Perform Authenticated Recovery (Only when 100% idle confirmed)
```

### Step 1: Verify Gateway Rejection
Check coordinator status to confirm admission is closed:
```powershell
python -m resource_coordinator.cli status
```
Verify output shows:
- `Service State: reconciliation_required` (or `stopped`)
- `Ready: False`
- `Restart inhibited: True`

### Step 2: Verify Miner Process State Out-of-Band
Open Windows Task Manager or Process Explorer:
- Check whether `krig-miner.exe` is running.
- If `krig-miner.exe` is running and consuming GPU resources unexpectedly:
  - If coordinator owned the process: Check supervisor logs in `resource-coordinator.log`.
  - If manual termination is required by operator safety policy: End the task manually via Task Manager. Record the PID, command line, and termination time.

### Step 3: Verify LM Studio Out-of-Band
In the LM Studio UI:
- Verify whether active token generation is taking place.
- If an inference request was in-flight and hung: Cancel the generation in LM Studio UI or unload the model.
- Confirm GPU memory and compute utilization return to idle baseline in `nvidia-smi`:
  ```powershell
  nvidia-smi --query-gpu=utilization.gpu,utilization.memory,memory.used,power.draw --format=csv
  ```

---

## 4. State Recovery & Re-admission Gate

The coordinator will **NEVER** automatically resume mining or re-open admission after an emergency abort.

To recover the coordinator service:
1. Ensure both LM Studio inference and mining processes are confirmed idle out-of-band.
2. Obtain or set the `RESOURCE_COORDINATOR_RECOVERY_TOKEN` in the environment.
3. Issue the authenticated recovery command with explicit operator evidence:
   ```powershell
   $env:RESOURCE_COORDINATOR_RECOVERY_TOKEN = "your-secure-operator-token"
   python -m resource_coordinator.cli recover --resource gpu.inference --force --reason "Operator verified out-of-band that LM Studio and Krig are stopped"
   ```
4. If the service was stopped or in reconciliation required, restart the coordinator with reviewed configuration:
   ```powershell
   python -m resource_coordinator.cli serve --config config.private.yaml
   ```
