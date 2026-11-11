# Failure Isolation, Rollback, and Emergency Decoupling (Phase 08)

**Document Version:** 1.0.0  
**Phase:** Phase 08 — Public HTTPS Readiness, Funnel Lifecycle, and Final Action-Safety Gates  
**Module:** `modules/remote_control`  
**Repository:** `MaxCarlson/scripts`  

---

## 1. Emergency Kill Switch Procedures

If unauthorized traffic, suspicious requests, or security anomalies are detected on the public internet endpoint, immediately execute the emergency kill switch.

### Primary Command Line Deactivation
Execute the operator disable command:
```powershell
scripts-remote-control external disable -a
```

### Direct Tailscale Command Fallback
If the Python CLI is unresponsive, invoke the native Tailscale binary directly from PowerShell:
```powershell
# Modern Tailscale direct Funnel disable
tailscale funnel --https=8443 off

# Legacy syntax fallback (if running older Tailscale daemon)
tailscale funnel 8443 off
tailscale serve --https=8443 off
```

### Windows Process Termination (Total Isolation)
If immediate local server shutdown is required:
```powershell
# Stop any running scripts-remote-control or uvicorn processes
Get-Process -Name "python" | Where-Object { $_.CommandLine -like "*remote_control*" } | Stop-Process -Force
```

---

## 2. Decoupling & Failure Scenarios

The architecture is designed to fail closed and maintain strict isolation between subsystem failures.

### Scenario A: Tailscale Service or Funnel Outage
- **Symptom:** Public URL `https://<node>.<tailnet>.ts.net:8443` is unreachable from mobile cellular internet.
- **Subsystem Impact:**
  - Local `remote_control` server continues running on `127.0.0.1:8443`.
  - Notifications broker continues receiving and processing system events.
  - Telegram bot notifications continue uninterrupted.
  - Windows desktop toast notifications continue uninterrupted.
  - Healthchecks.io heartbeats continue reporting host liveness.
- **Operator Action:**
  - Verify local server health: `scripts-remote-control status`.
  - Connect via existing private fallback: Router WireGuard VPN -> access `http://192.168.1.x:8443` or local loopback.
  - Inspect Tailscale service status: `scripts-remote-control external doctor`.

### Scenario B: Workstation Power Loss or Network Disconnect
- **Symptom:** Workstation is offline.
- **Subsystem Impact:**
  - Both local server and Tailscale Funnel are unreachable.
  - Telegram bot cannot deliver messages from the local broker.
  - Healthchecks.io detects missed heartbeat pings (within 5 minutes).
  - Healthchecks.io independently dispatches an off-host outage alert to the operator's phone via email/Telegram.
- **Operator Action:**
  - Investigate workstation physical power and local network connectivity.

### Scenario C: Durable Safety Barrier Triggered (`locked_unresolved`)

#### Mechanism (Mandatory Amendment 1)
When an external mutating action is dispatched, if an unexpected fault occurs:
- `asyncio.TimeoutError` during dispatch.
- Unhandled adapter exception during dispatch.
- Target subsystem returns `outcome_unknown`.

The system refuses to guess the execution outcome. It permanently seals the target resource by recording an active barrier in `action_resource_barriers` table with status `locked_unresolved`.

> **Mandatory Invariant (Amendment 1):**
> Neither transient lock lease expiry nor background process death (PID death) clears a safety barrier. An unresolved mutation remains locked against any further automated or manual execution until authoritative evidence is provided.

#### Diagnosis & Verification
Inspect active barriers using read-only status:
```powershell
scripts-remote-control external status
```
Or run the diagnostic doctor:
```powershell
scripts-remote-control external doctor
```
> **Mandatory Invariant (Amendment 2):**
> `external doctor` and `external status` are strictly 100% read-only. They will **never** clear barriers or reconcile executions.

#### Authoritative Reconciliation Procedure
To reconcile an active barrier:
1. Conduct an independent inspection of the target subsystem (e.g. check broker database, inspect system event logs, or verify physical device state) to determine whether the mutation actually took effect.
2. Reconcile the barrier using the dedicated CLI command, providing authoritative source evidence verified by typed verifiers (`IncidentAcknowledgementVerifier`, etc.):
   ```powershell
   # Preview reconciliation (dry-run)
   scripts-remote-control reconcile-barrier --resource-key "notifications:incident:101" --evidence "Inspected broker DB: incident acknowledged at 14:32"

   # Authoritatively apply barrier clearance
   scripts-remote-control reconcile-barrier --resource-key "notifications:incident:101" --evidence "Inspected broker DB: incident acknowledged at 14:32" -a
   ```
   *Note:* Free-text overrides without verifiable typed evidence are rejected (`unsupported_verifier`). Barrier clearance is executed with atomic `execution_id` binding to prevent TOCTOU race conditions against concurrently posted barriers.

#### Strictly Prohibited Action: Resource Coordinator Recovery Override
Any attempt to manually override or clear an unresolved Resource Coordinator recovery barrier via generic CLI reconciliation is strictly rejected by `CoordinatorRecoveryVerifier`:
```powershell
scripts-remote-control reconcile-barrier --resource-key "resource:gpu.inference" --evidence "Manual check" -a
# Returns: Error: coordinator_recovery_prohibited
```
Production Resource Coordinator recovery remains disabled server-side (`capability_disabled`) and cannot be bypassed.

---

## 3. Credential & Device Revocation Procedures

If an enrolled mobile device is lost, stolen, or suspected of compromise:

### Step 1: Revoke the Specific Device
List devices and identify the device ID:
```powershell
scripts-remote-control status
```
Revoke the device:
```powershell
scripts-remote-control revoke-device --device-id <device_id>
```
This immediately invalidates all active sessions associated with the device and rejects any future requests presenting the device cookie.

### Step 2: Invalidate All Active Sessions
If the session token alone is known:
```powershell
scripts-remote-control revoke-session --session-id <session_id>
```

### Step 3: Rotate Operator Password and TOTP Seed
For complete identity compromise:
```powershell
# Reset password (invalidates all active sessions across all devices)
scripts-remote-control reset-password

# Generate new TOTP two-factor secret
scripts-remote-control reset-totp
```
Re-enroll your authenticator app with the newly generated secret.
