# Windows Desktop Interactive Notification Helper

## Overview

The Windows Desktop Notification Helper solves the Windows **Session 0 / background service UI isolation** boundary.

### The Problem
When notification publishers run as background processes, noninteractive scheduled tasks, or services in Session 0, Windows intentionally prevents them from creating UI elements or invoking desktop toast notification APIs into user desktop sessions. Furthermore, running a notification host with elevated (Administrator/SYSTEM) privileges is explicitly advised against by Microsoft and creates unnecessary security exposure.

### The Solution
The helper runs as a **non-elevated user-session process** in the logged-in operator's interactive session (Session 1+), launched at logon by a user-scoped Scheduled Task (`ScriptsNotificationsToastHelper`).

It exposes a private loopback HTTP listener (`http://127.0.0.1:1238`) bound strictly to `127.0.0.1` and secured with Bearer token authentication matching the shared broker authentication token file (`~/.local/share/scripts_notifications/token`).

## Architecture & Security Boundary

```
+---------------------------------------------------------+
| Session 0 / Background Services / Outbox Worker         |
|                                                         |
|   scripts-notify outbox run                             |
|          |                                              |
|          v  (HTTP POST http://127.0.0.1:1238/notify)    |
|             Authorization: Bearer <token>               |
+----------|----------------------------------------------+
           | Loopback IPC (Local only)
+----------v----------------------------------------------+
| Interactive User Session (Session 1+, Non-Elevated)     |
|                                                         |
|   ScriptsNotificationsToastHelper (helper.ps1)          |
|          |                                              |
|          v  WinRT ToastNotificationManager / AppNotification
|   Windows Action Center & Desktop Toast Popup           |
|          |                                              |
|          v  (User clicks notification)                  |
|   Opens Read-Only Dashboard (https://... ONLY)          |
+---------------------------------------------------------+
```

### Threat Mitigation
1. **No Remote Code Execution**: The helper exposes NO command execution, shell spawning, or process launch endpoints. The only action a toast can perform is navigating the user's default browser to a verified `https://` dashboard URL via the Windows shell protocol handler.
2. **Local Token Authorization**: All endpoints require a valid Bearer token matching the 256-bit token file stored with user-only ACLs.
3. **Payload Sanitization**: Input titles and bodies are truncated and XML-escaped to prevent XML injection or parser denial-of-service.
4. **Non-Elevated**: Runs strictly with standard user privileges (`asInvoker`).

## Environment Rationale & Implementations
- **PowerShell WinRT Runner (`helper.ps1`)**: Production implementation utilizing Windows PowerShell 5.1 / PowerShell 7 built-in WinRT projections (`Windows.UI.Notifications.ToastNotificationManager` and `Windows.Data.Xml.Dom.XmlDocument`). Requires zero third-party packages or SDK compilation.
- **C# / Windows App SDK (`Program.cs`, `ScriptsNotificationsToastHelper.csproj`)**: Provided as the reference unpackaged desktop application implementation if a .NET SDK is provisioned. On systems without a .NET SDK installed (such as host environments with runtimes only), `helper.ps1` serves as the zero-dependency runner.

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | Bearer Token | Returns health status, session ID, user, and uptime |
| `POST` | `/notify` | Bearer Token | Dispatches a toast notification |
| `POST` | `/shutdown` | Bearer Token | Cleanly terminates the helper process |

## Payload Format (`POST /notify`)

```json
{
  "title": "Database Disk Space Warning",
  "body": "Volume D: is at 91% capacity.",
  "severity": "warning",
  "incident_id": "inc-01234567",
  "dashboard_url": "https://dashboard.example.com/incidents/inc-01234567"
}
```
