# Operator Quickstart: Notifications & Remote Control (Phase 09)

**Document Version:** 1.0.0  
**Phase:** Phase 09 — Adoption, Release Integration, and Operational Readiness  
**Target Audience:** Workstation Operator  
**Zero-Spend Assurance:** 100% free; requires no paid subscriptions or custom domains.  

---

## 1. Fast Health & Release Check

Run the unified read-only diagnostic check to inspect storage, provider enrollment, outbox queues, and active barriers:

```powershell
scripts-notify release-check
```

For scriptable machine-readable JSON:

```powershell
scripts-notify release-check -j
```

---

## 2. Initial Setup & Enrollment

### Step 2.1: Bootstrap Operator Identity & Two-Factor Authentication
Bootstrap the single operator credentials and enroll RFC 6238 TOTP:

```powershell
scripts-remote-control bootstrap
```
- Set a strong operator password (stored as salted Argon2id hash in `~/.scripts/remote_control/auth.db`).
- Scan the printed QR code / URI into your authenticator app (e.g. Aegis, Google Authenticator, Bitwarden).
- Confirm the generated 6-digit TOTP code to finalize enrollment.

### Step 2.2: Telegram Android Delivery Setup (Optional)
To receive mobile push notifications without maintaining active VPNs:

1. Create a bot with `@BotFather` on Telegram and copy the bot token.
2. Enroll the bot and link your Telegram chat ID:
   ```powershell
   scripts-notify telegram enroll --bot-token "123456:ABC-DEF..." --chat-id "123456789"
   ```
3. Test delivery in safe dry-run preview:
   ```powershell
   scripts-notify telegram test
   ```
4. Verify actual transmission:
   ```powershell
   scripts-notify telegram test -a
   ```

### Step 2.3: Windows Desktop Toast Notifications
Ensure desktop notifications display for the active interactive user session:

1. Check listener status:
   ```powershell
   scripts-notify windows status
   ```
2. Start the interactive helper listener (`helper.ps1` on `http://127.0.0.1:1238`):
   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File modules/notifications/windows_helper/helper.ps1
   ```

### Step 2.4: Off-Host Outage Monitoring (Healthchecks.io)
Ensure independent host-down alerts if the workstation powers down or network fails:

1. Create a free check on Healthchecks.io with a 5-minute interval.
2. Configure the ping URL (stored with owner-only ACLs):
   ```powershell
   scripts-notify heartbeat configure --ping-url "https://hc-ping.com/your-uuid-here" --interval 5
   ```
3. Inspect the scheduled task registration plan (dry-run):
   ```powershell
   scripts-notify heartbeat install
   ```

---

## 3. Daily Operations & Incident Monitoring

### Step 3.1: Start Local Dashboard
Launch the mobile-optimized PWA on the Windows loopback interface:

```powershell
scripts-remote-control serve --port 8443
```
- Open `https://127.0.0.1:8443` in your browser.
- Log in with operator password + TOTP code.

### Step 3.2: Inspect Incidents via CLI
To list currently tracked incidents:

```powershell
scripts-notify incidents list
```

To view details for a specific incident:

```powershell
scripts-notify incidents get <incident_id>
```

### Step 3.3: Guarded Incident Acknowledgement
From the Web PWA:
- Tap an active incident (`open` or `reopened`).
- Review incident summary and occurrence history.
- Tap **Acknowledge**, enter your 6-digit TOTP code, and confirm.

From the CLI:
```powershell
scripts-notify incidents acknowledge <incident_id> -a --actor "operator"
```

---

## 4. Controlled Public Access (Tailscale Funnel)

> **Mandatory Rule:** Public Funnel activation requires explicit operator approval and must follow the preflight verification sequence.

### Step 4.1: Run Preflight Health Check
Verify all 17 security and operational prerequisites:

```powershell
scripts-remote-control external doctor
```
Ensure `ready_for_public_enable: True`.

### Step 4.2: Inspect Dry-Run Plan
```powershell
scripts-remote-control external plan --port 8443 --public-port 8443
```

### Step 4.3: Operator-Approved Enablement
Ensure the web server is actively listening on port 8443, then execute:

```powershell
scripts-remote-control external enable -a --port 8443 --public-port 8443
```

### Step 4.4: Emergency Immediate Teardown
To revoke public Funnel reachability instantly:

```powershell
scripts-remote-control external disable -a
```
The local service, Telegram notifications, and desktop helper remain fully operational.
