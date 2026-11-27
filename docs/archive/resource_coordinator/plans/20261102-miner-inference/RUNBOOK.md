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

Tracked production configuration template:
[`modules/resource_coordinator/config.production-template.yaml`](file:///C:/Users/mcarls/src/scripts/.worktrees/miner-inference-coordination-20261102/modules/resource_coordinator/config.production-template.yaml)

```yaml
version: "1.0"

service:
  listen_host: "127.0.0.1"
  listen_port: 1235
  upstream_url: "http://127.0.0.1:1234"
  # Persistent writable state directory outside ephemeral git worktrees:
  state_persistence_path: "C:\\Users\\mcarls\\.resource_coordinator\\coordinator_state.json"

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
      - "<YOUR_WALLET_ADDRESS>/<YOUR_WORKER_NAME>"
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

### Creating Local Deployment Configuration
To configure the service for local host execution outside disposable git worktrees:
1. Create the persistent configuration and state directory:
   ```powershell
   New-Item -ItemType Directory -Force -Path "$HOME\.resource_coordinator"
   ```
2. Copy the template to your local path:
   ```powershell
   Copy-Item modules\resource_coordinator\config.production-template.yaml "$HOME\.resource_coordinator\config.yaml"
   # Alternatively, create a git-ignored file: modules\resource_coordinator\config.local.yaml
   ```
3. Set your authorized pool wallet and worker name in place of `<YOUR_WALLET_ADDRESS>/<YOUR_WORKER_NAME>`. Never commit wallet credentials to Git.
4. Verify that binary and working directory paths match your host installation (`C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\krig-miner.exe`).
5. Validate the configuration via preflight before starting:
   ```powershell
   python -m resource_coordinator.cli preflight -c "$HOME\.resource_coordinator\config.yaml"
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
From the repository root or deployment folder:

```powershell
# Initial Deployment (first-boot: initializes clean durable state journal if it does not exist):
$env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
python -m resource_coordinator.cli serve `
    -c "$HOME\.resource_coordinator\config.yaml" `
    --first-boot `
    --start-process krig_miner `
    --stop-process-on-shutdown krig_miner

# Normal Service Restart (resumes and reconciles existing durable state):
$env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
python -m resource_coordinator.cli serve `
    -c "$HOME\.resource_coordinator\config.yaml" `
    --start-process krig_miner `
    --stop-process-on-shutdown krig_miner
```

**Startup Flags Explained:**
- `--start-process krig_miner`: Instructs the coordinator to explicitly launch the configured mining process under coordinator ownership once the service reaches `ready` state.
- `--stop-process-on-shutdown krig_miner`: Guarantees that when the coordinator is stopped (via `Ctrl+C` or service stop), the child KRig process and its descendants are cleanly terminated.
- `--first-boot`: Initializes a brand-new durable state journal on disk if one does not already exist. **Do NOT pass `--first-boot` on routine restarts**, because normal restarts must reconcile any in-flight requests recorded in the existing journal rather than bypassing them.

### Inspecting Service Health & Status
```powershell
curl http://127.0.0.1:1235/_coordinator/status
```
Example Response:
```json
{
  "status": "online",
  "service_state": "ready",
  "is_ready": true,
  "upstream_url": "http://127.0.0.1:1234",
  "processes": {
    "krig_miner": {
      "state": "running",
      "pid": 60904,
      "lifecycle_owner": "coordinator",
      "is_coordinator_owned": true,
      "was_stopped_by_coordinator": false
    }
  },
  "gpu_inference": {
    "active_count": 0,
    "pending_count": 0,
    "is_cooling_down": false,
    "cooldown_remaining": 0.0,
    "is_restart_inhibited": false,
    "inhibition": null
  }
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

## 4. Startup, Shutdown & Crash Recovery Safety

### One-time migration gate — 2026-11-06 (not executed)

The review branch is `feature/miner-inference-coordination-20261102` at
`0e3db84f`; local `main` is `f6aac8b9`. They share merge base `bf6d3be3`
and have diverged (main is 29 commits ahead, the feature is 12 commits ahead
at this checkpoint). `git merge-tree --write-tree main feature/...` completed
without textual conflicts, but the branches have **not** been merged. Review
the full affected-module diff and run tests on the eventual merge result before
requesting deployment authorization.

The current logon task is `ResourceCoordinator-KRig-UserLogon`, principal
`mcarls` with interactive logon and limited run level. Its launcher passes
`--start-process krig_miner --stop-process-on-shutdown krig_miner`, reads
`C:\Users\mcarls\.resource_coordinator\config.yaml`, and starts code from
`C:\Users\mcarls\src\scripts`. There is no SYSTEM boot task. The checked live
state had one ready coordinator, zero active/pending requests, and coordinator-
owned KRig PID 49928. That process did not have the requested GPU flags.

The existing process does not expose the new authenticated miner or lifecycle
routes (`miner status` returns 404). It cannot use the new safe shutdown path.
Do not terminate its scheduled task, use abort, force-kill a process, or reboot
as a substitute. A controlled stop mechanism for this legacy hidden task is
still required before switching code. If no supported graceful signal can be
verified for that task instance, stop here and preserve the running service and
miner.

The shared operator credential exists at
`C:\Users\mcarls\.resource_coordinator\secrets\operator-token`; `auth doctor`
verified file readability, token format, and ACL entries for `mcarls` and
LocalSystem without printing the secret. `auth reinitialize` was tested against
the live listener and correctly refused to rotate it. The service task runs as
`mcarls`, so it resolves the same default profile path. A future SYSTEM task
must set `RESOURCE_COORDINATOR_TOKEN_FILE` to this exact path. SYSTEM access is
present in the ACL; no SYSTEM task currently exists to test actual runtime
access.

Once merge/deployment is separately authorized and a graceful legacy stop path
is verified, the migration sequence is:

1. Recheck status, inference clients, miner PID/ownership, config paths, and
   listener immediately before the change. Back up `config.yaml` and the
   durable state/lock metadata without exposing credentials; record file hashes.
2. Validate the integrated source, Python import paths, LM Studio upstream,
   configured miner executable, 10-second cooldown, and stop-on-shutdown flag.
3. Stop new requests, wait until active and pending counts reach zero, and
   require no restart inhibition. Use only the verified graceful stop mechanism.
4. Confirm the old coordinator and owned miner have exited and the instance
   lock is released. If any identity or exit is uncertain, do not start another
   owner.
5. Start the integrated service with the existing config and normal-restart
   arguments (no `--first-boot`). Confirm exactly one coordinator and one
   coordinator-owned miner, then verify actual KRig flags, pool activity, and
   append-only log output.
6. Verify inference through `:1235`, automatic stop before forwarding, and
   restart after completion/cooldown. Preserve existing model identity/context
   during gaming checks. Use mock tests for failure injection.

Rollback only after the new process has relinquished ownership and the lock is
released. Restore the backed-up code/configuration and durable state only after
checking that the older version can read that journal format. If the miner
fails to restart, retain the safety hold and evidence; never launch a second
miner while ownership is uncertain. TUI implementation remains blocked until
these live acceptance gates pass.

1. **Preflight Refusal of Conflicting External Miners:**
   - On startup, the coordinator actively scans host processes for existing unmanaged instances of the target executable (`krig-miner.exe`).
   - If an unowned external miner is running, the service fails closed and refuses to start, preventing dual-ownership collisions, overlapping GPU compute thrashing, or clock interference.
   - External miners must be stopped by the operator before the coordinator is launched.

2. **Single-Instance Host Ownership:**
   - An OS-level single-instance file lock (`coordinator_state.lock` via `msvcrt.locking` on Windows) is acquired exclusively upon launch.
   - If a duplicate coordinator instance is launched by a user, scheduled task, or background agent, it fails closed immediately without spawning competing processes, acquiring leases, or touching hardware.

3. **Strict Non-Adoption of Foreign Processes:**
   - The coordinator strictly manages only processes it has spawned directly (`adopt_external: false`).
   - Foreign processes (such as manual mining launched via `start-prl.ps1`, LM Studio on `:1234`, or OpenCode workers on PIDs `47108`/`63836`) are never adopted, signaled, or terminated.

4. **Durable Journal Reconciliation & Unresolved Prior Inference:**
   - Before upstream dispatch, every request is atomically committed to the durable state journal as `POSSIBLY_FORWARDED`.
   - On coordinator crash, abrupt process kill, or host reboot, any request not marked `TERMINAL_VERIFIED` is replayed on startup as a persistent `RestartInhibition` on `gpu.inference`.
   - The miner will **never** automatically restart after an unverified crash until an operator confirms upstream idle and clears the hold via `POST /_coordinator/recover`.
   - **Safety Invariant:** A fresh journal (`--first-boot`) must **never** be used to bypass an existing unresolved safety state or crash hold. Bypassing an unresolved journal risks restarting the miner while upstream inference is still executing.

5. **Unexpected Miner Exit Watchdog:**
   - If the coordinator-owned miner crashes while the system is safe-idle:
     - The supervisor executes bounded exponential backoff restarts (1s, 2s, 4s).
     - If crashes exceed 3 consecutive attempts, it emits `process.crash_loop_inhibited` and permanently latches restart inhibition on `gpu.inference` to protect the host.

6. **Host Services Protection:**
   - LM Studio (`:1234`), LLM Monitor (`:8789`), and local OpenCode workers are invariant host infrastructure and are never stopped, restarted, or altered by the Resource Coordinator.

---

## 5. Five-Stage Production Rollout Plan

To transition Miner / Local LLM Coordination from validated branch to production service safely, execute the following staged deployment:

### Stage 1: Coordinator-Only Service Verification
1. Verify LM Studio is listening on `127.0.0.1:1234` with `qwen38_23GB` loaded:
   ```powershell
   python -c "import httpx; r = httpx.get('http://127.0.0.1:1234/api/v0/models'); print([(m['id'], m['state']) for m in r.json().get('data', []) if m.get('state') == 'loaded'])"
   ```
2. Start Resource Coordinator standalone on port `1235` (using your local persistent configuration):
   ```powershell
   $env:PYTHONPATH = "modules/resource_coordinator;modules/llm_monitor"
   # Initial deployment only (--first-boot initializes new journal; omit on subsequent restarts):
   python -m resource_coordinator.cli serve `
       -c "$HOME\.resource_coordinator\config.yaml" `
       --first-boot `
       --start-process krig_miner `
       --stop-process-on-shutdown krig_miner
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
