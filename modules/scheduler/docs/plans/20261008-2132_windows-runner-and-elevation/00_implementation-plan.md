# Windows Runner and Unattended Elevation

## Objective

Make scheduler recurrence work reliably on Windows by providing an explicitly installed Task Scheduler logon runner, accessible from both CLI-only setup and the TUI. Scheduled `admin=True` tasks should run directly when Task Scheduler has already provided a highest-privilege token, without opening a UAC prompt each run.

## Scope

- Add `scheduler setup windows-runner install|status|start|remove`.
- Require Windows runner setup before normal CLI or TUI use, with a prominent setup-only TUI state and a red CLI warning.
- Provide `scheduler setup windows` as the direct first-time install command while preserving the longer spelling as an alias.
- Add equivalent status, install/update, start, and remove actions in the TUI configuration workflow.
- Register a per-user logon task with `RunLevel Highest`, an interactive logon token, the selected scheduler data file, an explicit Python executable, and restart settings.
- Require the one-time elevation needed to install the task. Do not store a password or use `SYSTEM`/S4U.
- Require explicit confirmation before a manual start that may execute due/catch-up schedules.
- Detect an already elevated process in the executor and execute child commands directly; fix the UAC fallback to wait and return the child's real exit code.
- Add unit tests with mocked PowerShell/process calls. Never create a live task in automated tests.
- Update module documentation, active handoffs, plan status, and package/registry version.

## Acceptance Criteria

1. CLI install registers a logon task for the launching user, at highest privileges, referencing the configured JSON data file and daemon interval.
2. CLI status is read-only and emits machine-readable JSON.
3. CLI start is blocked unless `--yes` is supplied; TUI start requires an explicit confirmation.
4. TUI exposes the same lifecycle actions through its configuration workflow.
5. Already elevated Windows execution avoids another UAC prompt; non-elevated fallback waits for its child and preserves its exit code.
6. Tests cover runner definition, privilege/logon settings, quoting, CLI/TUI routing, no-confirmation guard, and executor behavior without touching the live Windows task registry.
7. README explains that the daemon starts at logon and stops at sign-out, and that catch-up work may run when started.
8. Incomplete setup blocks normal scheduler operations and warns before help; Linux setup remains deferred.

## Out of Scope

- Installing/removing a live task as part of this code change.
- Automatically starting the daemon during registration; registration waits for the next user logon. Manual start is a separate, guarded action.
- Guaranteeing `winget` package upgrades succeed without user interaction; that depends on the packages and sources on the machine.
