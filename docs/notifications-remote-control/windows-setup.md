# Windows Desktop Notifications & Interactive Helper Setup Guide (Phase 03)

## 1. Architecture Overview

Phase 03 provides reliable Windows 11 desktop toast notifications from independent background processes without elevating background brokers or exposing the system to privilege escalation risks.

### The Session 0 / Desktop Isolation Boundary
Background brokers, scheduled jobs, and services on Windows frequently run in **Session 0** (noninteractive service session). Since Windows Vista, Session 0 processes are strictly prevented by the operating system kernel from displaying UI elements, dialog boxes, or toast notifications on interactive user desktops. Furthermore, running a notification host with elevated (Administrator or SYSTEM) privileges is explicitly advised against by Microsoft security guidance.

### The Solution: Non-Elevated User-Session Helper
To bridge this boundary cleanly and safely:
1. **Interactive Session Helper (`helper.ps1` / `ScriptsNotificationsToastHelper`)**:
   Runs as a standard, non-elevated user-session process in the logged-in operator's session (Session 1+). It is started automatically at user logon by a scoped Task Scheduler job (`ScriptsNotificationsToastHelper`).
2. **Authenticated Loopback IPC**:
   The helper exposes a loopback HTTP interface bound strictly to `127.0.0.1:1238`. All requests require Bearer token authentication matching the shared broker authentication token file stored with owner-only access controls (`~/.local/share/scripts_notifications/token` or `~/.scripts/notifications/secrets/broker-token`).
3. **Strict Capability Limits**:
   The helper accepts NO executable commands, shell arguments, or recovery mutation instructions. It only accepts sanitized notification text and an optional read-only HTTPS dashboard URL. Clicking a toast notification activates the dashboard URL via the Windows shell protocol handler (`https://...` only).
4. **Multi-Provider Isolation (N09)**:
   Windows desktop delivery and Telegram mobile delivery are completely decoupled. If the user is logged off or the helper is stopped, Windows delivery reports `retryable_error` (`session_unavailable`) while Telegram alerts continue to deliver unaffected.

---

## 2. Environment Discovery & Runtime Selection

During implementation and verification on Windows 11 (Build 10.0.26300), the following platform capabilities were identified:

| Component | Status | Operational Note |
|---|---|---|
| **.NET SDK** | *Not Found* | `dotnet --version` exits with code 1 (`No .NET SDKs were found`). Build tasks using `dotnet build` are unavailable. |
| **.NET Runtimes** | Present | `Microsoft.WindowsDesktop.App` (8.0, 9.0, 10.0) runtimes installed. |
| **PowerShell 7 (`pwsh.exe`)** | Present (7.6.1) | Used for cross-platform and modular execution. |
| **Windows PowerShell (`powershell.exe`)** | Present (5.1) | Features full native WinRT runtime projections (`Windows.UI.Notifications.ToastNotificationManager` and `Windows.Data.Xml.Dom.XmlDocument`). |
| **BurntToast Module** | Present (1.1.0) | Installed in user modules directory. |

### Decision & Tradeoff: Zero-Dependency PowerShell WinRT Helper
Per Section 4.1 instructions, rather than requiring the operator to install a multi-gigabyte .NET Developer SDK to compile a native C# binary, `modules/notifications/windows_helper/helper.ps1` serves as the primary production runner.
- **Advantages:** Zero compile-time prerequisites, native WinRT toast integration via built-in Windows PowerShell 5.1 / PowerShell 7, instant deployment, lightweight memory footprint.
- **Reference C# Project:** For environments with .NET SDKs installed, `ScriptsNotificationsToastHelper.csproj` and `Program.cs` are provided in `modules/notifications/windows_helper/` as the C# reference unpackaged desktop application.

---

## 3. Command-Line Management (`scripts-notify windows`)

All administrative and operational mutations default to **dry-run** mode and require `-a/--apply` to execute real system changes.

### 3.1 Check Helper & Scheduled Task Status
```powershell
scripts-notify windows status
scripts-notify windows status -j
```
Sample JSON output:
```json
{
  "ok": true,
  "task_name": "ScriptsNotificationsToastHelper",
  "task_installed": false,
  "task_state": "not_found",
  "helper_running": false,
  "helper_port": 1238,
  "token_file": "C:\\Users\\mcarls\\.scripts\\notifications\\secrets\\broker-token",
  "helper_script": "C:\\Users\\mcarls\\src\\scripts\\modules\\notifications\\windows_helper\\helper.ps1",
  "helper_details": {}
}
```

### 3.2 Install Logon Scheduled Task
By default, running `install` previews the task parameters:
```powershell
scripts-notify windows install
```
Output:
```text
Dry-run: pass -a/--apply to register the Windows Scheduled Task.
Target task: ScriptsNotificationsToastHelper (executing powershell.exe at logon)
```

To register the scheduled task under the current user's logon trigger:
```powershell
scripts-notify windows install -a
```

### 3.3 Test Toast Notification
To preview a test notification:
```powershell
scripts-notify windows test
```

To send a live desktop toast notification to the running helper:
```powershell
scripts-notify windows test -a
```

### 3.4 Uninstall Scheduled Task
To remove the scheduled task and terminate any active helper:
```powershell
scripts-notify windows uninstall -a
```

---

## 4. Provider Registry & Outbox Integration

The Windows desktop provider is registered under the identifier `windows`.

### Outbox Dispatch
When publishing an event targeted to desktop:
```powershell
scripts-notify publish -j '{"schema_version":1,"event_id":"...","source":"scheduler","kind":"task.failed","incident_key":"backup:db","severity":"critical","occurred_at":"2026-11-11T12:00:00Z","summary":"Daily backup failed","lifecycle":"open"}' -p "windows,telegram"
```
The outbox queues two independent items:
1. `provider_id="windows"`
2. `provider_id="telegram"`

When `scripts-notify outbox run` executes:
- If the desktop helper is responsive: `windows` transitions to `provider_accepted`.
- If the desktop helper is offline: `windows` transitions to `retryable_error` (`session_unavailable`) with a backoff retry, while `telegram` delivers immediately.

### Provider Testing
```powershell
scripts-notify providers test -p windows -a
```

---

## 5. Security & Threat Mitigation (N10)

1. **Authentication:**
   All helper endpoints (`/notify`, `/health`, `/shutdown`) validate `Authorization: Bearer <token>`. Unauthorized requests receive `401 Unauthorized`.
2. **XML Escaping & Injection Immunity:**
   Notification titles and bodies are sanitized and escaped (`&`, `<`, `>`, `"`, `'`) before being embedded into the WinRT toast XML template. Control characters are stripped.
3. **Payload Truncation:**
   Titles are bounded to 128 characters; message bodies are bounded to 512 characters. Requests over 32 KB are rejected with `400 Bad Request`.
4. **URL Safety:**
   Toast click actions only support `https://` URLs without embedded user credentials. No arbitrary application paths or executables can be invoked.

---

## 6. Scheduler Notifier Migration Recommendations

In `modules/scheduler/scheduler/notifier.py`, the existing Windows notification fallback uses string-interpolated PowerShell invoking `System.Windows.Forms.NotifyIcon`:
```python
# Legacy pattern to be migrated:
script = f'''
[void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms");
$obj = New-Object System.Windows.Forms.NotifyIcon;
$obj.BalloonTipTitle = "{title}";
$obj.BalloonTipText = "{message}";
$obj.ShowBalloonTip(5000);
'''
```

### Recommended Backward-Compatible Migration Path
1. **Primary Transport**: Update `Notifier.notify()` to publish events to `scripts-notify` via the public Python API (`IncidentLifecycleEngine` or HTTP loopback broker).
2. **Fallback Transport**: If `scripts-notify` is not running or unconfigured, keep a hardened desktop fallback that passes arguments via `subprocess.run(["powershell.exe", "-File", ...])` without string interpolation, avoiding shell injection risks.
3. **Coordination Note**: Do not alter `modules/scheduler/` until Phase 03 acceptance is approved by repository maintainers.
