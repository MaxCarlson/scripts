# PrivExec Operator Readiness & Windows Validation Runbook

All non-privileged synthetic unit, adversarial, and local named-pipe IPC tests run without elevation. The 5 gates below govern elevated deployment, real Windows account isolation, and live Resource Coordinator H4 qualification.

## Security Mode Distinction

- **`SameUserDev` (Development / Accidental-Misuse Containment):** Broker and agent run under the same Windows user account. Per Microsoft guidance, same-desktop UAC elevation is **not** a security boundary against a compromised agent.
- **`CrossAccountIsolated` (Stronger OS Isolation):** Broker runs under a dedicated privileged operator account (`<OPERATOR>`), and the agent runs under a separate non-administrator account (`<AGENT>`).

---

## Gate 1 — Elevated Installation (Requires Operator Elevation)

1. Build the broker:

   ```powershell
   pwsh -NoProfile -File .\scripts\Build-PrivExecBroker.ps1 -IncludeTests
   ```

2. Preview installation plan (read-only dry-run):

   ```powershell
   pwsh -NoProfile -File .\scripts\Install-PrivExec.ps1 -Mode CrossAccountIsolated `
       -OperatorAccount "XERES\<OPERATOR>" -AgentAccount "XERES\<AGENT>" `
       -H4SourceDir "C:\Users\mcarls\src\scripts\.worktrees\rc-h4-task-discovery-20261115\modules\resource_coordinator\tools\h4_qualification" `
       -Json
   ```

3. Perform authorized installation:

   ```powershell
   pwsh -NoProfile -File .\scripts\Install-PrivExec.ps1 -Apply -Mode CrossAccountIsolated `
       -OperatorAccount "XERES\<OPERATOR>" -AgentAccount "XERES\<AGENT>" `
       -H4SourceDir "C:\Users\mcarls\src\scripts\.worktrees\rc-h4-task-discovery-20261115\modules\resource_coordinator\tools\h4_qualification" `
       -Json
   ```

4. Verify ACLs and agent write denial:

   ```powershell
   icacls C:\ProgramData\PrivExec\descriptors
   icacls C:\ProgramData\PrivExec\adapters
   icacls C:\ProgramData\PrivExec\state
   ```

   Expected: `<AGENT>` has `(OI)(CI)RX` only on `bin`, `descriptors`, `adapters`, `h4_scripts`; zero write permissions anywhere under `C:\ProgramData\PrivExec`; zero access to `C:\ProgramData\PrivExec\state`.

---

## Gate 2 — Cross-Account Isolation (Requires Separate Operator & Non-Admin Agent Accounts)

1. As `<OPERATOR>` (elevated), create an operator grant JSON with `<AGENT_SID>` and start the broker:

   ```powershell
   privexec broker start -c C:\ProgramData\PrivExec\operator-grant.json `
       -b C:\ProgramData\PrivExec\bin\PrivExecBroker.dll `
       -d C:\ProgramData\PrivExec\descriptors -s C:\ProgramData\PrivExec\state -g
   ```

2. As `<AGENT>` (non-administrator account):
   - `privexec status` -> succeeds and reports active session.
   - `privexec broker stop` -> denied (`operator_only_action`).
   - `Add-Content C:\ProgramData\PrivExec\adapters\Invoke-H4PreflightAdapter.ps1 "#test"` -> `Access is denied`.
   - `privexec run synthetic.echo -t synth-target-1 -T synthetic -p .\forged-sid.json` (with `"sid"`/`"authorized"`) -> rejected (`forbidden_property`).
3. As a third unrelated Windows account `<OTHER_USER>`:
   - `privexec status` -> `PipeAccessDeniedError` (`ERROR_ACCESS_DENIED`).

---

## Gate 3 — Live H4 Read-Only Preflight (Requires Explicit Operator Approval)

1. Verify VM `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`) and protected checkpoint (`9f45b469-382c-4be0-a50e-7a71384c7922`) read-only.
2. Start broker with a read-only grant (`allowed_capabilities: ["h4.preflight"]`, `allow_mutation: false`, `allowed_targets: ["d8483f98-8884-4758-abd1-cd6107c83c03"]`, `-g` for operator guest credential prompt).
3. As `<AGENT>`:

   ```powershell
   privexec run h4.preflight -t d8483f98-8884-4758-abd1-cd6107c83c03 -T hyperv_vm
   privexec result <operation_id> -f json
   ```

4. Confirm `state == "succeeded"`, `exit_code == 0`, and zero host/guest mutations occurred.

---

## Gate 4 — Live H4 Mutation (Requires Separate Explicit Approval Per Stage)

Never grant `All` or unrestricted `h4.qualify` stages. Authorize one exact stage at a time (`allowed_h4_stages: ["Setup"]` for Setup; `["Acceptance"]` only when separately approved):

```powershell
# Setup (with grant allow_mutation=true, allowed_mutation_capabilities=["h4.qualify"], allowed_h4_stages=["Setup"])
privexec run h4.qualify -t d8483f98-8884-4758-abd1-cd6107c83c03 -T hyperv_vm -p .\setup-stage.json -A

# Recovery inspection (read-only default) or authorized recovery (separate h4.recover grant)
privexec run h4.recover -t d8483f98-8884-4758-abd1-cd6107c83c03 -T hyperv_vm
```

---

## Gate 5 — Final Integration

Merge `feat/privexec-session-broker-20261119` into `main` only after Gates 1–4 pass, all tests pass, and the operator explicitly authorizes integration.
