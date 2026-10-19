# Supervised Live Acceptance Test Plan

**Module:** `modules/resource_coordinator`  
**Document version:** 1.0  
**Status:** Acceptance Test Plan for Supervised Live Deployment  
**Target Platform:** Windows 11 / NVIDIA GeForce RTX 5090 (32 GB VRAM)  
**Target Services:** LM Studio 0.3.x (Port 1234) / Krig Miner 1.5.6 (PEARL) / Coordinator Gateway (Port 1235)  
**Safety Classification:** **HUMAN-SUPERVISED ONLY** (Autonomous live execution strictly prohibited)  

---

## 1. Safety Protocols and Prerequisites

> [!CAUTION]
> Under no circumstances may an AI agent execute this live test plan autonomously. A human operator must execute or explicitly authorize each live command. If unexpected GPU thrashing, driver resets, or process hangs occur, immediately execute Section 6 (Emergency Abort & Rollback).

### 1.1 Pre-Flight Environmental Verification

Before initiating any coordinator commands:
1. **NVIDIA Driver and GPU Health:**
   ```powershell
   nvidia-smi
   ```
   Verify:
   - GPU Name: `NVIDIA GeForce RTX 5090`
   - Driver Version: Verified compatible (570+ series recommended).
   - VRAM: ~32607 MiB total.
   - Persistence Mode: On / Default.
2. **LM Studio Upstream Availability:**
   Ensure LM Studio is running in Server Mode listening on `127.0.0.1:1234`.
   ```powershell
   curl -s http://127.0.0.1:1234/v1/models
   ```
   Must return HTTP 200 with loaded model list (e.g. `qwen2.5-coder-32b-instruct`).
3. **No Unmanaged Miner Instances:**
   ```powershell
   tasklist | findstr /i "krig"
   ```
   Must return no running processes before Step 1.

---

## 2. Configuration Setup

Copy the shipped template to a local runtime configuration:
```powershell
cp modules/resource_coordinator/config.supervised-template.yaml modules/resource_coordinator/config.supervised.yaml
```

Edit `modules/resource_coordinator/config.supervised.yaml`:
1. Provide the actual authorized pool URL and user wallet/worker string for PEARL mining.
2. Validate configuration:
   ```powershell
   python -m resource_coordinator.cli config validate modules/resource_coordinator/config.supervised.yaml
   ```
   Must output: `Configuration valid.`

---

## 3. Step-by-Step Supervised Test Procedure

### Phase 1: Read-Only System Diagnostics
Run the non-blocking hardware diagnostic:
```powershell
python -m resource_coordinator.cli diagnose
```
**Acceptance Criteria:**
- Output displays CPU usage %, GPU utilization %, GPU VRAM used/total, and power draw in Watts.
- Exit code is 0.

---

### Phase 2: Coordinator Launch and Miner Supervised Start
Launch the Resource Coordinator in a dedicated terminal window:
```powershell
python -m resource_coordinator.cli start --config modules/resource_coordinator/config.supervised.yaml
```
In a second terminal, verify initial state:
```powershell
python -m resource_coordinator.cli status
```
**Acceptance Criteria:**
- Gateway is listening on `127.0.0.1:1235`.
- Process `krig_miner` state is `STOPPED`.
- Active leases: 0, Pending: 0, Cooldown: inactive.

Start the miner under coordinator supervision:
```powershell
python -m resource_coordinator.cli start-process krig_miner
```
**Acceptance Criteria:**
- Krig spawns in a new console window with `CREATE_NEW_PROCESS_GROUP`.
- `resource-coordinator status` reports `krig_miner` as `RUNNING` with `lifecycle_owner: coordinator` and valid PID.
- `resource-coordinator diagnose` shows GPU power draw rising to mining targets (~250-450W depending on clocks) and VRAM allocated.

---

### Phase 3: Single Synchronous Inference Arbitration
Send a single non-streaming chat completion request through the coordinator gateway:
```powershell
curl -X POST http://127.0.0.1:1235/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{"model": "qwen2.5-coder-32b-instruct", "messages": [{"role": "user", "content": "Respond with the single word: OK"}], "stream": false}'
```

**Acceptance Criteria (Observed in Coordinator Terminal):**
1. Event `resource.lease_requested` logged immediately.
2. Cooldown cancelled (if any).
3. Policy `prioritize-local-inference` triggers `StopProcessAction("krig_miner")`.
4. Coordinator sends `CTRL_BREAK_EVENT` to Krig's process group.
5. Krig terminates gracefully; coordinator confirms `STOPPED` via PID table.
6. Request is forwarded to LM Studio (`127.0.0.1:1234`).
7. Client receives HTTP 200 with response `{"choices": [{"message": {"content": "OK"}}]}` and response header `x-coordinator-request-id`.
8. Lease is released; coordinator enters 60-second idle cooldown (`resource.cooldown_started`).

---

### Phase 4: Idle Cooldown and Mining Resumption
Do not send any requests for 65 seconds.
Monitor status:
```powershell
python -m resource_coordinator.cli status
```
**Acceptance Criteria:**
- For the first 60 seconds, `krig_miner` remains `STOPPED`. Status reports `is_cooling_down: True` with decreasing remaining seconds.
- At $T = 60s$, event `resource.idle` is emitted.
- Policy executes `StartProcessAction("krig_miner")`.
- Krig restarts in a new console window.
- Status reports `RUNNING` with a new verified PID and coordinator ownership.

---

### Phase 5: Streaming Cancellation and Protective Hold
Send a streaming request with a large token prompt, then abort the client mid-stream:
```powershell
# In PowerShell, start curl streaming and hit Ctrl+C after the first few tokens appear:
curl -N -X POST http://127.0.0.1:1235/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{"model": "qwen2.5-coder-32b-instruct", "messages": [{"role": "user", "content": "Write a 1000-word essay about distributed operating systems."}], "stream": true}'
```
Press `Ctrl+C` after 3 seconds.

**Acceptance Criteria:**
1. Krig stopped cleanly prior to stream start.
2. Client disconnect caught by gateway exception handler (`ClientDisconnect` / `CancelledError`).
3. Gateway emits `resource.restart_inhibited` with reason `indeterminate_cancellation: client_disconnected_mid_stream`.
4. Wait 90 seconds. **Krig must NOT restart.**
5. `resource-coordinator status` reports:
   - `Restart Inhibited: True`
   - Reason: `indeterminate_cancellation`
   - Holder: `<request_id>`

---

### Phase 6: Administrative Recovery
With the restart inhibited:
1. Verify host GPU state:
   ```powershell
   python -m resource_coordinator.cli diagnose
   ```
   Ensure LM Studio is not consuming compute resources.
2. Clear the protective inhibition:
   ```powershell
   python -m resource_coordinator.cli recover --resource gpu.inference
   ```
**Acceptance Criteria:**
- Output reports: `Restart inhibition cleared for resource 'gpu.inference'.`
- 60-second idle cooldown begins.
- At expiration, Krig restarts normally.

---

## 4. Acceptance Sign-Off Matrix

| Test Phase | Verification Item | Expected Result | Pass / Fail | Operator Signature |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1** | Read-only Hardware Diagnostics | CPU, GPU VRAM, Power reported via CLI | [ ] Pass | |
| **Phase 2** | Supervised Miner Start | Krig spawned in console, PID verified | [ ] Pass | |
| **Phase 3** | Inference Stop Arbitration | Krig stopped before request reaches LM Studio | [ ] Pass | |
| **Phase 3** | Clean Inference Response | HTTP 200, valid completion, request ID header | [ ] Pass | |
| **Phase 4** | 60s Idle Cooldown | Miner remains stopped during full 60s window | [ ] Pass | |
| **Phase 4** | Automatic Miner Resumption | Miner restarts with new verified PID | [ ] Pass | |
| **Phase 5** | Mid-Stream Client Abort | Protective restart inhibition latched | [ ] Pass | |
| **Phase 5** | Inhibition Non-Resumption | Miner does NOT restart after timeout | [ ] Pass | |
| **Phase 6** | Administrative Recovery | `recover` clears hold, cooldown resumes miner | [ ] Pass | |

---

## 5. Failure Modes and Triage Guide

| Symptom | Root Cause | Remediation |
| :--- | :--- | :--- |
| `VetoOperation: Policy action failed` | Miner failed to terminate within timeout (10s) | Check if Krig console is frozen or prompt dialog is open. Verify `allow_force_termination: false` is honored. Terminate manually. |
| `HTTP 502 Bad Gateway` | LM Studio port 1234 is closed or crashed | Verify LM Studio server is running: `curl http://127.0.0.1:1234/v1/models`. |
| `RuntimeError: Cannot recover a resource with active leases` | Operator ran `recover` while inference was actively executing | Wait for inference requests to complete before administrative recovery. |
| Krig restarts immediately during inference | External supervisor (Kryptex service) active | Check Services (`services.msc`) for background Kryptex launcher and stop it. |

---

## 6. Emergency Abort & Rollback Procedures

If an unrecoverable state, driver lockup, or GPU OOM crash occurs:

1. **Stop Coordinator Process:**
   In coordinator terminal, press `Ctrl+C` (or `taskkill /F /IM python.exe`).
2. **Force Kill Miner:**
   ```powershell
   taskkill /F /IM krig-miner.exe
   ```
3. **Verify GPU State:**
   ```powershell
   nvidia-smi
   ```
   If memory is locked by a zombie process, restart LM Studio or reboot host if driver crashed.
4. **Direct Client Rollback:**
   Point client applications (`lmst`, `lmc`, benchmarks) directly back to `http://127.0.0.1:1234`, bypassing port 1235 completely.
