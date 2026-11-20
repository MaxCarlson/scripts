# PrivExec Interface Contract & Architecture (Phase 0)

**Plan:** `20261119-privexec-session-broker`  
**Stage:** Phase 0 — Repository baseline and contract  
**Date:** 2026-11-19

## 1. Repository & Worktree Baseline

- **Primary repo root (untouched):** `C:\Users\mcarls\src\scripts` (`main` at `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`; contains untracked `lifecycle_audit_bundle_*.md`)
- **Isolated PrivExec worktree:** `C:\Users\mcarls\src\scripts-privexec`
- **Branch:** `feat/privexec-session-broker-20261119`
- **Base commit SHA:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b` (latest integrated `main`)
- **H4 reference worktree (read-only inspection only):** `C:\Users\mcarls\src\scripts\.worktrees\rc-h4-task-discovery-20261115` on `fix/rc-h4-task-discovery-20261115` (`ea6ad23fe705bc828f06a99ccf1ab3477e621d49`)

## 2. Toolchain Selection

### Python
- **Version:** `>=3.11` (verified `Python 3.12.10`, `pytest 9.0.3`, `ruff 0.14.8` on host).
- **Dependencies:** Standard library only (`argparse`, `json`, `pathlib`, `uuid`, `ctypes` / Win32 named-pipe client I/O on Windows, plus `cross_platform` optional or clean OS guard).

### .NET / C# Broker
- **Target Framework:** `.NET 10 LTS` (`net10.0-windows`).
- **Host environment finding:** The host currently has `Microsoft.NETCore.App` `8.0.34`, `9.0.23`, and `10.0.15` runtimes installed in `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\`, with **no `.NET SDK`** (`C:\Program Files\dotnet\sdk` absent). However, Visual Studio 2022 (`Community` and `BuildTools`) provides Roslyn `csc.exe` `4.14.0-3.26424.7`.
- **Zero-NuGet / Dual-build strategy:**
  1. Standard `PrivExecBroker.csproj` (`net10.0-windows`) with zero NuGet package dependencies (`System.IO.Pipes`, `System.IO.Pipes.AccessControl`, `System.Security.Principal.Windows`, `System.Text.Json`, `System.Security.Cryptography`, and Win32 `winsqlite3.dll` P/Invoke).
  2. `Build-PrivExecBroker.ps1` automatically uses `dotnet build` if a .NET SDK is available, and falls back to Roslyn `csc.exe` compiling against `Microsoft.NETCore.App\10.0.15` + generating `PrivExecBroker.runtimeconfig.json` so `dotnet PrivExecBroker.dll` runs natively on `.NET 10.0.15` even without an SDK installed.

## 3. Windows Account & ACL Security Model

1. **Same-user UAC mode (dev / accidental-misuse containment):**
   - Broker and agent run under the same Windows user account (broker elevated, agent non-elevated).
   - Provides application-level capability, target, mode, and expiry guardrails against accidental agent misuse.
   - **Explicit limitation:** Same-desktop UAC elevation is **not** a security boundary against a compromised agent (per Microsoft guidance).
2. **Cross-account isolated mode (stronger OS isolation):**
   - Broker runs under a dedicated privileged operator identity (`<OP_SID>`), separate from the non-administrator agent identity (`<AGENT_SID>`).
   - Named pipe ACL explicitly denies network (`NT AUTHORITY\NETWORK`) and remote/anonymous access, grants full control to `SYSTEM`, `Administrators`, and `<OP_SID>`, and grants `ReadWrite` (connect/pipe I/O, **not** `CreateNewInstance` or `WriteDac`) only to explicitly configured `<AGENT_SID>` list. Never uses `CurrentUserOnly` for cross-account deployments.
   - Protected installation root (e.g. `C:\ProgramData\PrivExec` or operator-configured path): owned by `Administrators`/`<OP_SID>`, read/execute for `<OP_SID>` and `SYSTEM`, no write access for `<AGENT_SID>`.
   - SQLite ledger & evidence directory: accessible only to `<OP_SID>`, `SYSTEM`, `Administrators` (agent reads sanitized results only via broker `result` IPC, or explicit read-only evidence staging if configured).

## 4. IPC Transport & Protocol v1 Contract

- **Transport:** Local Windows named pipe `\\.\pipe\<pipe_name>` (default `privexec-broker-v1`).
- **Wire framing:** 4-byte unsigned little-endian length prefix (`uint32`), followed by UTF-8 JSON body. Maximum frame size: `4 * 1024 * 1024` bytes (4 MiB).
- **Client authentication:** Server calls `NamedPipeServerStream.RunAsClient(...)` and inspects `WindowsIdentity.GetCurrent(TokenAccessLevels.Query)` (SID + account name) server-side. Client-supplied identity fields are rejected.
- **Actions:**
  - `status`: returns broker version, session ID, expiration, allowed capabilities (names/modes), active mutation count, protocol version.
  - `run`: submits a capability execution request.
  - `result`: retrieves an existing operation record by `operation_id` (read-only, never re-executes).
  - `revoke` / `shutdown`: **operator-only** control action (accepted only from operator SID or local operator console; denied for non-operator agent SIDs).

### 4.1 `run` Request Schema (v1)

```json
{
  "protocol_version": 1,
  "action": "run",
  "request_id": "req-20261119-001",
  "capability": "h4.preflight",
  "target": {
    "type": "hyperv_vm",
    "id": "d8483f98-8884-4758-abd1-cd6107c83c03"
  },
  "mode": "dry_run",
  "parameters": {}
}
```

Strict validation rules:
- Unknown top-level properties are **rejected** (`400` / `invalid_request`).
- Forbidden properties (e.g. `authorized`, `sid`, `user`, `role`, `executable`, `script`, `command`, `credential`, `password`, `approval`) anywhere in top-level or parameters are **rejected**.
- `mode` must be `"dry_run"` or `"apply"`. Missing/default is `"dry_run"`.
- `request_id` must match `^[A-Za-z0-9._:-]{1,128}$`.
- `capability` must match `^[a-z0-9._-]{1,64}$`.

### 4.2 `run` / `result` Response Schema (v1)

```json
{
  "protocol_version": 1,
  "operation_id": "op-...",
  "request_id": "req-20261119-001",
  "capability": "h4.preflight",
  "target_id": "d8483f98-8884-4758-abd1-cd6107c83c03",
  "mode": "dry_run",
  "state": "succeeded",
  "authorized": true,
  "exit_code": 0,
  "started_at": "2026-11-19T14:50:00.0000000Z",
  "finished_at": "2026-11-19T14:50:01.0000000Z",
  "diagnostic_category": null,
  "result": {},
  "evidence": [],
  "postcondition_verified": true,
  "error": null
}
```

State machine:
`requested -> validated -> (denied | approved -> executing -> (succeeded | failed | outcome_unknown))`

## 5. Fixed Capability Descriptor Schema

Stored as immutable JSON files in a protected directory loaded at broker startup:

```json
{
  "schema_version": 1,
  "capability_id": "synthetic.echo",
  "version": "1.0.0",
  "runner_type": "python",
  "executable_path": "C:\\ProgramData\\PrivExec\\runtime\\python.exe",
  "executable_sha256": "<optional-or-pinned-64hex>",
  "script_path": "C:\\ProgramData\\PrivExec\\scripts\\synthetic_echo.py",
  "script_sha256": "<required-64hex>",
  "working_directory": "C:\\ProgramData\\PrivExec\\work",
  "target_types": ["synthetic"],
  "allowed_targets": ["target-1"],
  "supports_dry_run": true,
  "supports_apply": false,
  "is_mutating": false,
  "max_duration_seconds": 30,
  "requires_guest_credential": false,
  "fixed_args": ["-B", "{script_path}"],
  "parameter_schema": {
    "message": {
      "type": "string",
      "required": false,
      "pattern": "^[A-Za-z0-9 _.-]{0,128}$",
      "cli_flag": "--message"
    }
  }
}
```

Before every execution, the broker:
1. Checks that `executable_path`, `script_path`, and `working_directory` have no ancestor or leaf reparse points / symlinks / junctions.
2. Computes SHA-256 of `script_path` (and `executable_path` if `executable_sha256` is configured) and verifies exact match.
3. Validates every client parameter against `parameter_schema` (strictly rejecting unknown parameters, shell metacharacters, or out-of-range values).
4. Launches with `UseShellExecute = false` and `ArgumentList` (no shell interpolation).

## 6. H4 Integration Seam (Read-Only Verified from `fix/rc-h4-task-discovery-20261115`)

Inspected files on `fix/rc-h4-task-discovery-20261115` (`ea6ad23f`):
- `Invoke-H4GuestQualification.ps1`:
  - `-Stage`: `Preflight | Setup | Checkpoint | Acceptance | All`
  - Mutation switches: `-Apply` (`-a`) and `-AuthorizeGuestMutation`; `-WhatIf` suppresses mutations.
  - Note: Does **not** expose an `Install` stage; `windows_acceptance.py` inside the guest bundle exposes `--profile install` (requiring PowerShell Direct into `RC-H4-Windows-Acceptance` `d8483f98-8884-4758-abd1-cd6107c83c03` / `DESKTOP-1ITSJV0`).
  - Accepts `-Credential ([pscredential])` (never logged or persisted), `-OperationId`, `-Json` (`-j`), pinned hashes (`ExpectedBundleSha256`, `ExpectedBootstrapSha256`, `ExpectedPythonSha256`, `ExpectedPwshSha256`), `-EvidenceRoot`.
- `Invoke-H4GuestRecovery.ps1`:
  - Default is read-only `--profile recover` dry-run.
  - `-StageBundle` stages verified v10 bundle; `-Apply` + `-AuthorizeGuestMutation` runs recovery apply + mandatory post-recovery read-only inventory.
  - Accepts `-Credential ([pscredential])`, `-OperationId`, `-Json` (`-j`), `-ProtectedCheckpointId` (`9f45b469-382c-4be0-a50e-7a71384c7922`), `-EvidenceRoot`.

PrivExec H4 adapters:
- `h4.preflight`: invokes staged `Invoke-H4PreflightAdapter.ps1` -> `Invoke-H4GuestQualification.ps1 -Stage Preflight -Json` (read-only; never passes `-Apply` or `-AuthorizeGuestMutation`).
- `h4.qualify`: invokes staged `Invoke-H4QualifyAdapter.ps1` with explicitly enumerated mode (`preflight`, `setup`, `acceptance`; excludes `All` and arbitrary checkpoint/lifecycle control; `setup` requires `-Apply` + grant; `acceptance` requires `-Apply` + `-AuthorizeGuestMutation` + separate acceptance grant).
- `h4.recover`: invokes staged `Invoke-H4RecoverAdapter.ps1` -> `Invoke-H4GuestRecovery.ps1 -Json` (defaults to read-only inspection; mutation requires `-Apply` + explicit recovery grant + preserves `ProtectedCheckpointId`).
- Guest `PSCredential` is constructed inside the broker/PowerShell adapter from operator-entered `SecureString` held only in broker process memory, passed via PowerShell `-Credential` object (never serialized to JSON, disk, environment variables, or CLI arguments).
