# PrivExec Normal-Agent Integration Guide

This guide documents how ordinary non-elevated Codex/Antigravity coding-agent sessions invoke PrivExec capabilities without manual command copying between terminals, while preserving Windows ACL isolation and explicit operator authorization.

## 1. Security Model & One-Time Protected Installation

- **Normal agent identity:** Codex/Antigravity sessions on `XERES` run as non-elevated `XERES\mcarls` (Medium Integrity Level; `BUILTIN\Administrators` is `deny-only`).
- **Critical ACL requirement:** `C:\ProgramData\PrivExec` (`bin`, `descriptors`, `adapters`, `h4_scripts`, `state`, `work`) **must not** grant `FullControl` or write access to `XERES\mcarls` directly. Only `NT AUTHORITY\SYSTEM` and `BUILTIN\Administrators` may have `FullControl` (so elevated `XERES\mcarls` has admin access via `BUILTIN\Administrators`, while non-elevated `XERES\mcarls` has zero write access).
- **Read-only agent access:** `XERES\PrivExecAgent` and `XERES\mcarls` receive `ReadAndExecute` only on `bin`, `client`, `descriptors`, `adapters`, and `h4_scripts`, and **no access** to `state` or `work`.

### Required One-Time Elevated Remediation / Installation

Run once in an **elevated Administrator PowerShell 7** terminal to rebind `C:\ProgramData\PrivExec` ACLs and stage the `privexec.cmd` / `privexec.ps1` client wrappers:

```powershell
pwsh -NoProfile -File C:\Users\mcarls\src\scripts-privexec\modules\privileged_execution\scripts\Install-PrivExec.ps1 `
    -Apply `
    -Mode CrossAccountIsolated `
    -OperatorAccount "XERES\mcarls" `
    -AgentAccount "XERES\PrivExecAgent" `
    -H4SourceDir "C:\Users\mcarls\src\scripts\.worktrees\rc-h4-task-discovery-20261115\modules\resource_coordinator\tools\h4_qualification"
```

## 2. Operator Authorization of Capability Grants

Grants are operator-controlled JSON policies (or explicit `Start-PrivExecSession.ps1` parameters) specifying:
- `allowed_client_sids`: Exact Windows SIDs permitted to connect (e.g., `XERES\mcarls` and/or `XERES\PrivExecAgent`).
- `allowed_capabilities`: Exact capability IDs (e.g., `h4.preflight`).
- `allowed_targets`: Exact target IDs (e.g., `d8483f98-8884-4758-abd1-cd6107c83c03`).
- `allow_mutation`, `allowed_mutation_capabilities`, `allowed_h4_stages`: Default `false` / empty.
- `ttl_seconds`: Clamped to `1..86400` seconds (default `1800`).

Because `C:\ProgramData\PrivExec\state` grants `FullControl` only to `SYSTEM` and `BUILTIN\Administrators`, non-elevated agents cannot create, read, or modify grant files.

## 3. Starting and Stopping Elevated Sessions

Start a time-limited, capability-scoped broker session from an **elevated Administrator PowerShell 7** terminal using `scripts/Start-PrivExecSession.ps1`:

```powershell
pwsh -NoProfile -File C:\Users\mcarls\src\scripts-privexec\modules\privileged_execution\scripts\Start-PrivExecSession.ps1 `
    -AllowedClientAccounts "XERES\mcarls","XERES\PrivExecAgent" `
    -AllowedCapabilities "h4.preflight" `
    -AllowedTargets "d8483f98-8884-4758-abd1-cd6107c83c03" `
    -TtlSeconds 1800 `
    -PromptGuestCredential
```

`Start-PrivExecSession.ps1` verifies that no non-administrator principal has write ACLs on `C:\ProgramData\PrivExec`, launches `C:\Program Files\dotnet\dotnet.exe C:\ProgramData\PrivExec\bin\PrivExecBroker.dll` on `\\.\pipe\privexec-broker-v1` (with zero Python in the elevated launch chain), and removes any temporary grant JSON on exit.

### Revoking or Stopping a Session

- Press `Ctrl+C` in the operator's broker console, **or**
- Run `C:\ProgramData\PrivExec\client\privexec.cmd broker stop` from an operator session.

## 4. Normal Autonomous Agent Requests

Once the operator has started a session, any authorized non-elevated coding-agent session can invoke PrivExec from **any** working directory using the staged wrapper (no `PYTHONPATH` setup required):

```powershell
# 1. Check broker reachability and authorized capabilities
C:\ProgramData\PrivExec\client\privexec.cmd status -f json

# 2. Execute an authorized read-only capability and consume JSON directly
C:\ProgramData\PrivExec\client\privexec.cmd run h4.preflight `
    -t d8483f98-8884-4758-abd1-cd6107c83c03 `
    -T hyperv_vm `
    -J '{"vm_name":"RC-H4-Windows-Acceptance","expected_guest_host":"DESKTOP-1ITSJV0"}'

# 3. Look up a persisted operation result without re-executing
C:\ProgramData\PrivExec\client\privexec.cmd result <operation_id>
```

From inside the repository, `modules\privileged_execution\scripts\privexec.cmd` (or `privexec.ps1`) provides the exact same interface.

## 5. Renewal and Expiration Behavior

- **Fail-closed expiration:** `SessionAuthorizer` rejects requests once `UtcNow >= ExpiresAtUtc` (`session_expired`).
- **Session renewal:** Because PrivExec intentionally does not install a Windows service or scheduled task (`creates_service = false`, `creates_task = false`), renewing an expired session or starting a new session after reboot requires the operator to re-run `Start-PrivExecSession.ps1` in an elevated PowerShell 7 terminal (up to `86400` seconds / 24 hours per session).
