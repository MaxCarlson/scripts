# H4 Reference Adapters

These PowerShell 7 adapters bridge PrivExec capability descriptors (`h4.preflight`, `h4.qualify`, `h4.recover`) to the staged Resource Coordinator H4 wrapper scripts without modifying `modules/resource_coordinator/**`.

## Verified H4 Entry Points (`fix/rc-h4-task-discovery-20261115`, `ea6ad23f`)

- **Host qualification wrapper:** `Invoke-H4GuestQualification.ps1`
  - Supported `-Stage` values: `Preflight`, `Setup`, `Checkpoint`, `Acceptance`, `All`
  - Mutation switches: `-Apply` (`-a`) and `-AuthorizeGuestMutation`
  - **Install-only note:** `Invoke-H4GuestQualification.ps1` does **not** expose an `Install` stage. The guest-side harness `windows_acceptance.py` exposes `--profile install` inside the verified guest bundle. Accordingly, `h4.qualify` exposes only `Preflight`, `Setup`, and `Acceptance` (excluding `All` and `Checkpoint` from blanket grants).
- **Host recovery wrapper:** `Invoke-H4GuestRecovery.ps1`
  - Default invocation is read-only recovery dry-run (`--profile recover`).
  - Mutation requires both `-Apply` and `-AuthorizeGuestMutation` and preserves `ProtectedCheckpointId` (`9f45b469-382c-4be0-a50e-7a71384c7922`).

## Credential Handling

When `requires_guest_credential: true` is set on an H4 descriptor, `PrivExecBroker` writes a single transient JSON line (`{"username","password"}`) from operator-held `SecureString` memory to the adapter's anonymous stdin stream and zeroes the transient BSTR immediately. Credentials are never written to disk, CLI arguments, environment variables, or logs.
