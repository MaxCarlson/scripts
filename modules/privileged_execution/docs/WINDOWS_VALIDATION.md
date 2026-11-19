# PrivExec Windows Security & H4 Validation Guide

All non-privileged synthetic unit and IPC tests run automatically without elevation. The procedures below verify real Windows privilege isolation, ACL enforcement, and live Resource Coordinator H4 qualification, which require explicit operator authorization.

## 1. Security Boundary Modes

- **Same-user UAC (`SameUserDev`)**: Broker runs elevated and agent runs non-elevated under the same Windows user account. This provides accidental-misuse containment only; per Microsoft guidance, same-desktop UAC is **not** a security boundary against a compromised agent.
- **Cross-account isolation (`CrossAccountIsolated`)**: Broker runs under a dedicated privileged operator account (`<OPERATOR_ACCOUNT>`), and the agent runs under a separate non-administrator account (`<AGENT_ACCOUNT>`).

## 2. Staged Installation Validation (Requires Operator Elevation)

Preview installation plan (safe, read-only):

```powershell
pwsh -NoProfile -File .\scripts\Install-PrivExec.ps1 -Mode CrossAccountIsolated `
    -OperatorAccount "XERES\<OPERATOR>" -AgentAccount "XERES\<AGENT>" `
    -H4SourceDir "C:\Path\To\resource_coordinator\tools\h4_qualification" -Json
```

Perform elevated installation (only when authorized):

```powershell
pwsh -NoProfile -File .\scripts\Install-PrivExec.ps1 -Apply -Mode CrossAccountIsolated `
    -OperatorAccount "XERES\<OPERATOR>" -AgentAccount "XERES\<AGENT>" `
    -H4SourceDir "C:\Path\To\resource_coordinator\tools\h4_qualification" -Json
```

Verify ACLs:

```powershell
icacls C:\ProgramData\PrivExec\descriptors
icacls C:\ProgramData\PrivExec\state
```

Expected: `<AGENT>` has `RX` only on `bin`, `descriptors`, `adapters`, `h4_scripts`; zero write permissions anywhere under `C:\ProgramData\PrivExec`; zero access to `C:\ProgramData\PrivExec\state`.

## 3. Cross-Account Pipe & SID Validation

1. As `<OPERATOR>` (elevated), start the broker with a grant JSON listing `<AGENT_SID>` (and NOT other SIDs):

   ```powershell
   privexec broker start -c C:\ProgramData\PrivExec\operator-grant.json `
       -d C:\ProgramData\PrivExec\descriptors -s C:\ProgramData\PrivExec\state -g
   ```

2. As `<AGENT>` (non-admin account):
   - `privexec status` -> succeeds and shows active session.
   - `privexec broker stop` -> denied (`operator_only_action`).
   - Attempt to write to `C:\ProgramData\PrivExec\adapters\Invoke-H4PreflightAdapter.ps1` -> `Access is denied`.
3. As a third unrelated local account `<OTHER_USER>`:
   - `privexec status` -> `PipeAccessDeniedError` (`ERROR_ACCESS_DENIED`).

## 4. H4 Qualification Workflow (Requires Explicit VM Authorization)

1. Read-only preflight (no VM mutation):

   ```powershell
   privexec run h4.preflight -t d8483f98-8884-4758-abd1-cd6107c83c03 -T hyperv_vm
   ```

2. Authorized setup (requires `h4.qualify` in `allowed_mutation_capabilities` and `allow_mutation: true`):

   ```powershell
   privexec run h4.qualify -t d8483f98-8884-4758-abd1-cd6107c83c03 -T hyperv_vm `
       -p .\setup-params.json -A
   ```

3. Recovery inspection / authorized recovery (requires separate `h4.recover` grant):

   ```powershell
   privexec run h4.recover -t d8483f98-8884-4758-abd1-cd6107c83c03 -T hyperv_vm
   ```
