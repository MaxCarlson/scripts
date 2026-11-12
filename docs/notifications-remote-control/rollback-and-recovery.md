# Operational Rollback, Incident Reconciliation & Disaster Recovery (Phase 09)

**Document Version:** 1.0.0  
**Phase:** Phase 09 — Adoption, Release Integration, and Operational Readiness  
**Target Audience:** Workstation Operator / Incident Responder  

---

## 1. Threat Scenarios & Emergency Action Matrix

| Emergency Scenario | Immediate Action Required | Command / Procedure | Data Loss Impact |
| :--- | :--- | :--- | :--- |
| **Suspected Public Exposure / Leak** | Terminate Tailscale Funnel immediately | `scripts-remote-control external disable -a` | Zero data loss. Local notifications continue. |
| **Lost / Compromised Operator Phone** | Revoke all operator sessions and enrolled devices | `scripts-remote-control revoke-session --all`<br>`scripts-remote-control revoke-device --device-id <id>` | Zero incident data loss; operator re-login required. |
| **Active Action Execution Barrier** | Investigate condition and reconcile barrier with evidence | `scripts-remote-control reconcile-barrier -a --barrier-id <id> --evidence "verified safe"` | Clears barrier; restores guarded mutation ability. |
| **Database Corruption / Disk Full** | Revert SQLite database from backup file | Copy latest `.db.bak` to `events.db` | Reverts events since last backup. |
| **Scheduler Notification Loop / Storm** | Disable broker routing in Scheduler configuration | Set `"use_notifications_broker": false` in scheduler config | Scheduler tasks continue unaffected using local fallback. |
| **Stuck Windows Helper Process** | Stop local helper listener | `POST http://127.0.0.1:1238/shutdown` with bearer token | Ephemeral listener terminates; notifications queue in outbox. |

---

## 2. Detailed Emergency Procedures

### 2.1 Immediate Funnel Teardown (Cut Public Access)

If suspicious network activity is detected or public exposure must be terminated instantly:

```powershell
scripts-remote-control external disable -a
```

Alternatively, direct Tailscale CLI fallback:
```powershell
tailscale funnel --https=8443 off
```

**Post-Teardown Verification:**
1. Verify Tailscale Funnel status is inactive:
   ```powershell
   scripts-remote-control external status
   ```
2. Verify from an external mobile device (cellular, Wi-Fi off) that the public URL returns connection refused / timeout.
3. Confirm local loopback service on `127.0.0.1:8443` remains responsive for workstation administration.

---

### 2.2 Operator Session & Device Revocation

If an operator handset is lost, stolen, or compromised:

1. Invalidate all active sessions across all devices:
   ```powershell
   scripts-remote-control revoke-session --all
   ```
2. Identify and revoke the specific device identifier:
   ```powershell
   scripts-remote-control status
   scripts-remote-control revoke-device --device-id <device_id>
   ```
3. Rotate the operator password and TOTP secret:
   ```powershell
   scripts-remote-control reset-password
   scripts-remote-control reset-totp
   ```

---

### 2.3 Reconciling Action Execution Barriers

When an action outcome is ambiguous (e.g., unexpected network disconnect or timeout during confirmation), the system sets a durable, fail-closed `action_resource_barriers` record to prevent duplicate mutation.

To reconcile:
1. Inspect the active barrier and reason:
   ```powershell
   scripts-remote-control external status
   ```
2. Manually verify the underlying resource state (e.g., confirm whether the incident was actually acknowledged or task completed).
3. Clear the barrier with authoritative operator justification:
   ```powershell
   scripts-remote-control reconcile-barrier -a --barrier-id <barrier_id> --evidence "Verified via host logs that task completed successfully with exit code 0."
   ```

---

### 2.4 Restoring SQLite Persistence from Backup

1. Stop any active processes accessing the database:
   - Stop `scripts-remote-control serve`
   - Stop outbox runner or scheduled tasks
2. Navigate to storage directory:
   ```powershell
   Set-Location "$env:USERPROFILE\.scripts\notifications"
   ```
3. Copy backup file over `events.db`:
   ```powershell
   Copy-Item "events.db.bak" "events.db" -Force
   Remove-Item "events.db-wal", "events.db-shm" -ErrorAction SilentlyContinue
   ```
4. Verify database integrity:
   ```powershell
   scripts-notify status
   ```

---

### 2.5 Removing Scheduled Tasks

If scheduled background tasks must be cleanly unregistered:

1. Coordinator Observer:
   ```powershell
   scripts-notify coordinator task uninstall -a
   ```
2. Heartbeat Runner:
   ```powershell
   scripts-notify heartbeat uninstall -a
   ```
3. Verify uninstallation:
   ```powershell
   scripts-notify release-check
   ```
