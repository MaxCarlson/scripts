# Independent Off-Host Outage Monitoring Setup Guide (Phase 04)

## 1. Architecture Overview & Topology

Phase 04 provides independent, off-host detection and phone alerting when the primary Windows workstation crashes, loses power, drops internet connectivity, or experiences catastrophic hardware failure.

### The "Dead Man's Snitch" Inversion
Internal watchdog processes running on the local host cannot alert an operator when the host itself dies or loses connectivity. To solve this without requiring costly external polling infrastructure, the system utilizes an outbound heartbeat (dead man's snitch) pattern via **Healthchecks.io**:

```
+-----------------------------------------------------------------------------------------+
| Primary Workstation (Windows 11)                                                        |
|                                                                                         |
|  [Windows Task Scheduler]                                                               |
|        |                                                                                |
|        | (every 5 minutes via Task Scheduler)                                          |
|        v                                                                                |
|  [scripts-notify heartbeat runner]  <--- Zero DB / Broker / Desktop Session Dependency  |
|        |                                                                                |
|        | (HTTPS GET/POST to hc-ping.com)                                                |
+--------|--------------------------------------------------------------------------------+
         |
         | (Encrypted Outbound Ping over Internet)
         v
+------------------------------------+
| Healthchecks.io Cloud Service      |
|                                    |
| (Independent Off-Host Monitoring)  |
| - Expects ping every 5 minutes     |
| - Grace period: 5 minutes          |
+------------------------------------+
         |
         | (If no ping received within 10 minutes)
         v
+------------------------------------+
| Telegram Cloud Platform            |
|                                    |
| (@HealthchecksBot Direct Alerts)   |
+------------------------------------+
         |
         | (Push Alert)
         v
+------------------------------------+
| Operator Android Phone             |
|                                    |
| "Host Alive is DOWN!"              |
+------------------------------------+
```

### Complete Independence (N12 / N13)
The host heartbeat mechanism operates with complete independence from other repository systems:
- **No Broker Daemon Dependency:** The heartbeat runs even if `scripts-notify` broker daemon is stopped or crashed.
- **No SQLite Database Dependency:** The runner does not open, read, lock, or migrate `events.db`.
- **No Local Telegram Provider Dependency:** Healthchecks.io delivers alerts directly to Telegram from the cloud; local Telegram enrollment failure or Telegram API rate limiting on the workstation does not impair outage alerts.
- **No Resource Coordinator Dependency:** Operates without any hooks, locks, or state queries against `modules/resource_coordinator/`.
- **No Interactive Desktop Session Dependency:** The scheduled task can execute under `CurrentUser` or `NT AUTHORITY\SYSTEM` regardless of whether an interactive user is logged into Windows.

---

## 2. Operator Onboarding & Zero-Cost Setup ($0 Spend)

Healthchecks.io offers a generous, fully featured **Hobbyist Plan ($0/month)** supporting up to 20 checks with full Telegram integration.

### Step 1: Create Healthchecks.io Account
1. Visit [https://healthchecks.io](https://healthchecks.io) and sign up for a free account.
2. Create a Project named `Workstation Monitoring` or `Homelab`.

### Step 2: Create the Host Liveness Check
1. Click **Add Check**.
2. Configure check settings:
   - **Name:** `Host Alive`
   - **Period:** `5 minutes` (Schedule interval)
   - **Grace Time:** `5 minutes` (Tolerance window before declaring an outage)
   - **Filter:** Leave default (HTTP GET / POST)
3. Note the generated unique Ping URL, e.g.:
   `https://hc-ping.com/b46a1e9c-4f7d-41a2-8e10-912837465abc`

### Step 3: Connect Telegram Integration via `@HealthchecksBot`
1. In the Healthchecks.io dashboard, navigate to **Integrations**.
2. Click **Add Integration** -> **Telegram**.
3. Follow the instructions to link `@HealthchecksBot` to your Telegram account or channel.
4. Ensure the `Host Alive` check is configured to dispatch notifications to the connected Telegram integration.

---

## 3. Workstation Configuration & Security Hardening

The secret UUID in the Ping URL allows anyone possessing it to send pings. The system enforces strict access control and secret sanitization across all layers.

### 3.1 Configure Healthchecks Secret
Save the ping URL securely. The CLI supports interactive masked input to prevent exposing secrets in PowerShell command history or process tables:

```powershell
# Interactive prompt (recommended: omits ping URL from shell history):
scripts-notify heartbeat configure -i 5 -a

# Explicit command-line configuration (-u/--url for URL, -i/--interval for interval in minutes):
scripts-notify heartbeat configure -u "https://hc-ping.com/b46a1e9c-4f7d-41a2-8e10-912837465abc" -i 5 -a

# Or via environment variable:
$env:NOTIFY_HEALTHCHECKS_PING_URL = "https://hc-ping.com/b46a1e9c-4f7d-41a2-8e10-912837465abc"
scripts-notify heartbeat configure -i 5 -a
```

### 3.2 Security Controls Enforced
1. **Owner-Restricted Filesystem ACLs & Fail-Secure Atomic Replacement:** Configuration is saved to `~/.scripts/notifications/secrets/healthchecks.json`. Windows `icacls` removes inheritance and restricts Full Control strictly to the user SID and `S-1-5-18` (`NT AUTHORITY\SYSTEM`). Writes use an unpredictable temporary file in the same directory (`mkstemp`), secure its permissions before replacement, and atomically swap it into place (`os.replace`). Any failure cleans up the temporary file and preserves the existing valid configuration. Symlinks and reparse points are explicitly rejected.
2. **HTTPS Scheme Enforcement:** Insecure `http://` URLs are rejected automatically unless `NOTIFICATIONS_ALLOW_INSECURE_PING=1` is set for offline unit tests.
3. **No Embedded Credentials:** URLs with embedded credentials (`https://user:pass@...`) are rejected by schema validation.
4. **Automatic Secret Redaction:** Ping UUIDs and slugs are redacted (`[REDACTED_PING_UUID]` / `[REDACTED_UUID]`) from all logs, stdout, error messages, and JSON status reports.
5. **Structured Process Ingestion:** When installing the Scheduled Task, arguments and paths are passed via structured JSON over `stdin` to PowerShell, completely preventing command injection, backtick expansion, or apostrophe quoting failures.

---

## 4. Scheduled Task Registration & Maintenance

### 4.1 Execution Modes: Headless vs Interactive-Only

The Windows Scheduled Task supports two distinct operational modes:

| Mode | Principal / Logon Type | Elevation Required? | Runs Logged Off? | Survives Reboots? | Recommended Use |
|---|---|---|---|---|---|
| **Headless (Recommended for 24/7)** | `NT AUTHORITY\SYSTEM` (`ServiceAccount`) | **Yes** (Administrator) | **Yes** | **Yes** (runs at boot before logon) | True 24/7 host outage and liveness monitoring |
| **Interactive-Only** | `CurrentUser` (`InteractiveToken`) | No | **No** (suspends when logged off) | **No** (waits for user to log on) | Local testing or unprivileged development |

> [!IMPORTANT]
> Microsoft Windows Task Scheduler strictly prevents `InteractiveToken` tasks from launching without an active user desktop session. To achieve true 24/7 off-host outage detection that alerts you when the host loses power or crashes and does not depend on a user being logged in, always register using `--headless` from an elevated Administrator prompt.

> [!CAUTION] Existing Task Overwrite Precaution
> Registration uses `Register-ScheduledTask -Force` in PowerShell, which automatically replaces and overwrites any existing task with the same name. Always inspect the currently registered task first via `scripts-notify heartbeat status` or `Get-ScheduledTask -TaskName ScriptsNotificationsHostHeartbeat` before applying changes.

### 4.2 Install Heartbeat Task
All mutations default to **dry-run** mode. Pass `-a/--apply` to execute real registrations:

```powershell
# Dry-run preview:
scripts-notify heartbeat install -i 5

# Register interactive-only task (standard user):
scripts-notify heartbeat install -i 5 -a

# Register headless task surviving reboots & logged-off state (requires Administrator PowerShell):
scripts-notify heartbeat install --headless -i 5 -a
```

### 4.3 Verify Status
```powershell
scripts-notify heartbeat status
scripts-notify heartbeat status -j
```
Sample output:
```text
Independent Outage Monitoring (Healthchecks.io) Status:
 - Configured: Yes
 - Check Name: Host Alive (5m interval)
 - Ping URL: https://hc-ping.com/[REDACTED_PING_UUID]
 - Scheduled Task (ScriptsNotificationsHostHeartbeat): Installed (State: Ready)
 - Execution Mode: headless (SYSTEM / ServiceAccount)
 - Logged-off Capable: Yes
 - Last Run: 11/11/2026 12:00:00 PM (Result: 0)
 - Next Run: 11/11/2026 12:05:00 PM
```

### 4.4 Windows-Local Logged-Off and Reboot Acceptance Procedure
To verify that the headless host heartbeat operates without an active user logon session without performing an unsolicited reboot:

1. **Register Headless Task:**
   Open PowerShell as Administrator and run:
   ```powershell
   scripts-notify heartbeat install --headless -i 5 -a
   ```
2. **Confirm Headless Identity:**
   ```powershell
   scripts-notify heartbeat status
   ```
   Verify that `Execution Mode` shows `headless (SYSTEM / ServiceAccount)` and `Logged-off Capable: Yes`.
3. **Trigger Manual Validation Ping:**
   ```powershell
   scripts-notify heartbeat test -a
   ```
   Confirm Healthchecks.io logs the successful ping.
4. **Logged-Off Test:**
   - Sign out of Windows (`Ctrl+Alt+Del` -> **Sign out**).
   - Wait 10 minutes with the workstation powered on at the Windows Login screen.
   - On your phone or secondary device, open the Healthchecks.io web dashboard and verify the `Host Alive` check received pings while the machine remained logged off.
5. **Reboot Acceptance (Optional operator maintenance):**
   - When ready for scheduled maintenance, restart the PC.
   - Leave the machine at the Windows lock screen for 6–8 minutes before logging in.
   - Log in and inspect the Task Scheduler history:
     ```powershell
     schtasks.exe /query /tn ScriptsNotificationsHostHeartbeat /v /fo csv
     ```
     Confirm the `Last Run Time` timestamp preceded your interactive logon.

### 4.5 Send Test Ping vs Direct Ping
```powershell
# Dry-run test verification (validates configuration and network without external mutation):
scripts-notify heartbeat test

# Live test transmission (REQUIRED: sends real external HTTP request to Healthchecks):
scripts-notify heartbeat test -a

# Direct one-shot ping (invoked by Scheduled Tasks / headless runner; has no -a flag):
scripts-notify heartbeat ping
```

### 4.6 Run Diagnostic Doctor
Verify end-to-end prerequisites (configuration presence, task state, and network connectivity to `hc-ping.com`):
```powershell
scripts-notify heartbeat doctor
```
Sample output:
```text
Heartbeat Doctor Diagnosis: HEALTHY
 [PASS] configuration: Configured for check 'Host Alive' (5m interval)
 [PASS] scheduled_task: Task 'ScriptsNotificationsHostHeartbeat' is Ready [Headless SYSTEM (runs logged off)] (Last result: 0)
 [PASS] network_connectivity: https://hc-ping.com responded with HTTP 200
```

### 4.7 Task Uninstallation & Repair
```powershell
# Repair configuration ACLs and task registration:
scripts-notify heartbeat repair -a

# Unregister scheduled task:
scripts-notify heartbeat uninstall -a
```

---

## 5. Failure Classification & Operational Playbook

When an outage alert fires in Telegram, use the following decision matrix to triage the failure:

| Alert State | Potential Causes | Diagnostic Action |
|---|---|---|
| **Host Alive is DOWN (Grace expired)** | 1. Complete power outage or hardware crash.<br>2. Workstation suspended / sleep mode entered.<br>3. ISP / home gateway network loss.<br>4. Windows Task Scheduler service stopped. | Check remote connectivity via phone (cellular). If remote SSH/Tailscale is unreachable, host has suffered physical power/network loss. If Tailscale is reachable, inspect `scripts-notify heartbeat doctor`. |
| **Pings failing with `dns_connect_error`** | DNS resolution failure or local network gateway failure. | Verify workstation Ethernet connection and router DNS. |
| **Pings failing with `timeout`** | Severe packet loss or upstream ISP throttling. | Inspect route to `hc-ping.com`. Default timeout is 10s. |
| **Pings failing with `tls_error`** | System clock drift, TLS interception proxy, or corrupted certificate store. | Verify Windows clock synchronization (`w32tm /resync`). |

### Handling Planned Maintenance
When rebooting, performing hardware upgrades, or taking the workstation down intentionally:
1. Open Healthchecks.io mobile web dashboard or send `/pause Host Alive` to `@HealthchecksBot`.
2. Perform workstation maintenance.
3. Once the workstation is back online, the periodic task will automatically resume pings and unpause the check.
