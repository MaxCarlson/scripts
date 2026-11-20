# PrivExec Dedicated Standard-User Agent Account Proposal

**Status:** **PROPOSAL — REQUIRES OPERATOR AUTHORIZATION**  
**Context:** Codex CLI `0.169.1` on `XERES` uses MXC (`prefer_mxc = true`, `windows.sandbox = "unelevated"`), `codex.exe sandbox` exits with `0xC0000142` (`STATUS_DLL_INIT_FAILED`) across default/unelevated/elevated overrides from non-Codex shells, and legacy `CodexSandboxOffline` (`...-1007`) has `setup_error.json: helper_unknown_error` with no externally usable credential.

---

## 1. Account Provisioning (Operator-Controlled)

- **Account:** `XERES\PrivExecAgent` (standard local user, member of `Users` only — **not** `Administrators` or `Hyper-V Administrators`).
- **Password:** Generated and held by the operator (e.g. Windows Credential Manager or interactive `Get-Credential`; never stored in Git, scripts, grant JSONs, or logs).
- **Installation ACLs:** Run `Install-PrivExec.ps1 -Apply -Mode CrossAccountIsolated -OperatorAccount "XERES\mcarls" -AgentAccount "XERES\PrivExecAgent" -H4SourceDir ...`
  - Grants `XERES\PrivExecAgent` `(OI)(CI)(RX)` only on `C:\ProgramData\PrivExec` (`bin`, `client`, `descriptors`, `adapters`, `h4_scripts`).
  - Denies/omits `XERES\PrivExecAgent` on `C:\ProgramData\PrivExec\state` and `C:\ProgramData\PrivExec\work`.
  - Purges stale temporary SID `S-1-5-21-...-1019` from all directories.

## 2. Trusted Elevated Broker Launch (Zero Python)

- Launch `PrivExecBroker.dll` directly via `C:\Program Files\dotnet\dotnet.exe` (writable only by `TrustedInstaller`, `SYSTEM`, `Administrators`), eliminating `.venv` (`CodexSandboxUsers:(M)`) and Python from the elevated launch chain:
  ```powershell
  & "C:\Program Files\dotnet\dotnet.exe" "C:\ProgramData\PrivExec\bin\PrivExecBroker.dll" `
      --pipe privexec-broker-v1 `
      --descriptors-dir "C:\ProgramData\PrivExec\descriptors" `
      --state-dir "C:\ProgramData\PrivExec\state" `
      --grant-file "C:\ProgramData\PrivExec\state\gate3-preflight-grant.json" `
      --ttl-seconds 300 --prompt-guest-credential
  ```

## 3. Authenticated Client Launch (`XERES\PrivExecAgent`)

- Launch the non-elevated client under `XERES\PrivExecAgent` with an isolated `TEMP`/`TMP`/`USERPROFILE` (never inheriting `C:\Users\mcarls\AppData\Local\Temp`), `PYTHONPATH=C:\ProgramData\PrivExec\client`, and `TokenImpersonationLevel.Impersonation` (built into `privexec.transport`):
  ```powershell
  $agentCred = Get-Credential -UserName 'XERES\PrivExecAgent' -Message 'Enter PrivExecAgent password'
  Start-Process -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' -Credential $agentCred `
      -WorkingDirectory 'C:\Users\PrivExecAgent' -Wait -NoNewWindow `
      -ArgumentList @('-NoProfile', '-Command', '$env:PYTHONPATH="C:\ProgramData\PrivExec\client"; whoami /user; python -m privexec.cli status')
  ```
- For Codex / Antigravity workflows: an operator-opened `XERES\PrivExecAgent` shell (or operator-authorized runner) executes `python -m privexec.cli run ...` and `result ...`, keeping `XERES\mcarls` completely separate from the unprivileged client SID.

## 4. Cleanup / Retirement

- Stop broker (`Ctrl+C` or `privexec.cli broker stop`) and delete temporary grant JSON files.
- To retire `XERES\PrivExecAgent` later: `Remove-LocalUser -Name PrivExecAgent` and re-run `Install-PrivExec.ps1` or `Uninstall-PrivExec.ps1`.
