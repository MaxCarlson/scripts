# Resource Coordinator & Miner Inference Coordination — Operational Runbook

**Target Architecture:**
```
Inference Client (OpenCode, Benchmark, IDE)
       │
       ▼ (Optional Telemetry & Recording)
LLM Monitor Gateway (:8788 / :8789)
       │
       ▼ (Lease Arbitration, Stop Barrier, 10s Monotonic Cooldown)
Resource Coordinator (:1235)
       │
       ▼ (Direct Local Inference)
LM Studio Upstream (:1234)
```

---

## 1. Port & Service Topology

| Component | Default Port | Description | In-Flight Safety Boundary |
|---|---|---|---|
| **LM Studio** | `1234` | Local model server hosting `qwen38-27b-q4km` (alias `qwen38_23GB`) | Never restart or terminate |
| **Resource Coordinator** | `1235` | Authoritative process & lease controller | Sole owner of child miner process |
| **LLM Monitor Gateway** | `8789` / `8788` | Observability & prompt recording proxy | Upstreams to Coordinator `:1235` |
| **OpenCode Workers** | `4096` / `4196` | Local coding agents | Never terminate host processes |

---

## 2. Configuration & Manifests

Production configuration file (validated on host):
[`modules/resource_coordinator/config.live-local.yaml`](file:///C:/Users/mcarls/src/scripts/.worktrees/miner-inference-coordination-20261102/modules/resource_coordinator/config.live-local.yaml)

```yaml
version: "1.0"

service:
  listen_host: "127.0.0.1"
  listen_port: 1235
  upstream_url: "http://127.0.0.1:1234"
  state_persistence_path: "C:\\Users\\mcarls\\src\\scripts\\.worktrees\\miner-inference-coordination-20261102\\modules\\resource_coordinator\\.live_acceptance_work\\coordinator_state.json"

resources:
  gpu.inference:
    type: "shared"
    cooldown_seconds: 10.0

processes:
  krig_miner:
    backend: "windows"
    executable: "C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6\\krig-miner.exe"
    working_directory: "C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6"
    arguments:
      - "--coin"
      - "pearl"
      - "--url"
      - "stratum+ssl://prl-us.kryptex.network:8048"
      - "--user"
      - "krxXPVG8JN/Xeres"
    stop_timeout_seconds: 10.0
    restart_cooldown_seconds: 10.0
    new_console: false
    allow_force_termination: true
    allow_external_stop: false
    allow_external_restart: false
    adopt_external: false

policies:
  - name: "pause_krig_for_inference"
    trigger_event: "lmstudio.inference_requested"
    target_process: "krig_miner"
    stop_process: true
    stop_timeout_seconds: 10.0
    resource: "gpu.inference"
    lease_type: "shared"
    cooldown_seconds: 10.0
    restart_process: true
    only_if_stopped_by_coordinator: true

  - name: "pause_krig_for_model_load"
    trigger_event: "lmstudio.model_load_requested"
    target_process: "krig_miner"
    stop_process: true
    stop_timeout_seconds: 10.0
    resource: "gpu.inference"
    lease_type: "exclusive"
    cooldown_seconds: 10.0
    restart_process: true
    only_if_stopped_by_coordinator: true
```

---

## 3. Operations & Lifecycle Commands

### Running Supervised Acceptance Trials
The coordinator CLI provides automated acceptance testing across three modes:
1. **Simulated (`simulated`):** In-memory fake process backend and mock upstream:
   ```powershell
   python -m resource_coordinator.cli accept -m simulated
   ```
2. **Disposable Windows Helper (`disposable_helper`):** Real Windows OS processes via `cscript.exe` helper:
   ```powershell
   python -m resource_coordinator.cli accept -m disposable_helper
   ```
3. **Live Hardware Acceptance (`live`):** Controlled hardware acceptance with real KRig + LM Studio:
   ```powershell
   # Stage 3: Single request trial
   python -m resource_coordinator.cli accept -c modules/resource_coordinator/config.live-local.yaml -m live --allow-live-lmstudio --allow-real-miner --trials T01

   # Stage 5: Concurrency and streaming trials
   python -m resource_coordinator.cli accept -c modules/resource_coordinator/config.live-local.yaml -m live --allow-live-lmstudio --allow-real-miner --trials T02 T03 T04
   ```

### Starting the Coordinator Service
From the repository root or worktree:
```powershell
$env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
python -m resource_coordinator.cli serve --config modules/resource_coordinator/config.supervised-template.yaml
```
*Note: On a brand new deployment without an existing state journal, add `--first-boot` to explicitly initialize the journal file.*

### Inspecting Service Health & Status
```powershell
curl http://127.0.0.1:1235/_coordinator/status
```
Example Response:
```json
{
  "service_state": "ready",
  "is_ready": true,
  "resources": {
    "gpu.inference": {
      "active_count": 0,
      "pending_count": 0,
      "is_restart_inhibited": false,
      "inhibition": null
    }
  },
  "managed_processes": ["krig"]
}
```

### Emergency Abort (Immediate Latch)
Halts traffic admission immediately and locks all mining restarts:
```powershell
$headers = @{ "Authorization" = "Bearer $env:RESOURCE_COORDINATOR_RECOVERY_TOKEN" }
$body = @{ "operator" = "admin"; "reason" = "Unscheduled maintenance" } | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:1235/_coordinator/abort" -Headers $headers -Body $body -ContentType "application/json"
```

### Clearing Holds & Operator Recovery
Clears restart inhibition after verifying upstream idle:
```powershell
$headers = @{ "Authorization" = "Bearer $env:RESOURCE_COORDINATOR_RECOVERY_TOKEN" }
$body = @{ "override" = $true; "operator" = "admin"; "reason" = "LM Studio confirmed idle" } | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:1235/_coordinator/recover?resource=gpu.inference" -Headers $headers -Body $body -ContentType "application/json"
```

---

## 4. Crash Recovery & Single-Instance Safety

1. **Single Owner Lock:**
   - A single-instance lock (`coordinator_state.lock`) is acquired upon launch via `msvcrt.locking`.
   - If a duplicate coordinator is launched by a user or script, it will fail closed immediately without spawning competing processes or touching existing leases.

2. **Durable Journal Reconciliation:**
   - Before upstream dispatch, every request is atomically committed as `POSSIBLY_FORWARDED`.
   - On coordinator crash or host restart, any request not marked `TERMINAL_VERIFIED` is replayed on startup as a `RestartInhibition` on `gpu.inference`.
   - The miner will **never** automatically restart after a crash until an operator clears the hold or upstream verifies completion.

3. **Unexpected Miner Exit Watchdog:**
   - If the coordinator-owned miner crashes while the system is safe-idle:
     - Attempts bounded exponential backoff restarts (1s, 2s, 4s).
     - If crashes exceed 3 consecutive attempts, it emits `process.crash_loop_inhibited` and permanently latches restart inhibition on `gpu.inference`.

---

## 5. Five-Stage Production Rollout Plan

To transition Miner / Local LLM Coordination from validated branch to production service safely, execute the following staged deployment:

### Stage 1: Coordinator-Only Service Verification
1. Verify LM Studio is listening on `127.0.0.1:1234` with `qwen38_23GB` loaded:
   ```powershell
   python -c "import httpx; r = httpx.get('http://127.0.0.1:1234/api/v0/models'); print([(m['id'], m['state']) for m in r.json().get('data', []) if m.get('state') == 'loaded'])"
   ```
2. Start Resource Coordinator standalone on port `1235`:
   ```powershell
   $env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
   python -m resource_coordinator.cli serve --config modules/resource_coordinator/config.live-local.yaml --first-boot
   ```
3. In a separate terminal, verify service health and readiness:
   ```powershell
   curl http://127.0.0.1:1235/_coordinator/status
   ```
   Confirm `service_state == "ready"` and `is_ready == true`.
4. Verify read-only model discovery passthrough:
   ```powershell
   curl http://127.0.0.1:1235/api/v0/models
   ```
   Confirm model list is returned without triggering process stops or acquiring leases.

### Stage 2: Single Test Client Verification
1. Send a single non-streaming test inference request directly to port `1235`:
   ```powershell
   $body = @{
       model = "qwen38_23GB"
       messages = @(@{ role = "user"; content = "Reply with OK" })
       max_tokens = 4
       temperature = 0.0
   } | ConvertTo-Json
   Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:1235/v1/chat/completions" -Body $body -ContentType "application/json"
   ```
2. Verify coordinator stop-before-forward barrier:
   - Miner process stops before LM Studio receives the request.
   - Inference succeeds with HTTP `200 OK`.
   - Cooldown timer (10.0s) begins.
   - Miner restarts automatically after cooldown expires.

### Stage 3: LLM Monitor Gateway Integration
1. Restart LLM Monitor web targeting the Coordinator on port `1235`:
   ```powershell
   python -m llm_monitor web -p 8789 -e http://127.0.0.1:1234 --gateway --gateway-upstream http://127.0.0.1:1235 -R content -n -d .../qualification.sqlite3
   ```
2. Send a test inference request through LLM Monitor on port `8789`:
   ```powershell
   Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8789/v1/chat/completions" -Body $body -ContentType "application/json"
   ```
3. Verify proxy chaining:
   `Client -> LLM Monitor (:8789) -> Resource Coordinator (:1235) -> LM Studio (:1234)`
   - LLM Monitor records prompt and response in SQLite qualification database.
   - Resource Coordinator arbitrates GPU lease and holds miner stopped during inference.

### Stage 4: OpenCode Worker Integration
1. Update OpenCode provider configuration in `opencode.json` to target LLM Monitor or Coordinator:
   ```json
   {
     "baseURL": "http://127.0.0.1:8789/v1"
   }
   ```
2. Issue a test coding request to OpenCode.
3. Verify streaming token delivery over SSE:
   - Incremental chunks flow without backpressure stalls.
   - Miner remains stopped throughout the generation.
   - Cooldown initiates upon stream termination (`[DONE]`).

### Stage 5: Normal Operation, Observability & Recovery
1. Operating state invariants:
   - Port 1235 handles all inference traffic with authoritative arbitration.
   - Driver power limit remains pinned at 600W.
   - Crash watchdog automatically recovers unexpected miner exits during safe-idle (1s, 2s, 4s backoff; max 3 retries).
2. Emergency Abort & Recovery:
   - To immediately stop admission and freeze mining:
     `POST http://127.0.0.1:1235/_coordinator/abort`
   - To clear operator holds after verifying LM Studio idle:
     `POST http://127.0.0.1:1235/_coordinator/recover?resource=gpu.inference`

---

## 6. Client Migration Reference & Rollback Guide

| Client | Configuration Location | Current Setting | Migrated Setting | Rollback Command |
|---|---|---|---|---|
| **Direct Inference** | Client HTTP baseUrl | `http://127.0.0.1:1234` | `http://127.0.0.1:1235` | Set baseUrl back to `:1234` |
| **Monitored Benchmark** | `llm-monitor web --gateway-upstream` | `http://127.0.0.1:1234` | `http://127.0.0.1:1235` | Restart monitor with `--gateway-upstream http://127.0.0.1:1234` |
| **OpenCode Local Agent** | `opencode.json` / provider config | `http://127.0.0.1:1234/v1` | `http://127.0.0.1:1235/v1` (or `:8789/v1`) | Revert `baseURL` in provider settings |

### Rollback Procedure
If any client encounters unexpected latency or errors:
1. Point the client's `baseURL` directly back to LM Studio at `http://127.0.0.1:1234/v1`.
2. Stop the Resource Coordinator service (CTRL+C or SIGINT).
3. If manual mining is desired, launch `Mining\start-prl.ps1` in an interactive PowerShell terminal.
4. Foreign processes started via `start-prl.ps1` will not be touched by the coordinator.
