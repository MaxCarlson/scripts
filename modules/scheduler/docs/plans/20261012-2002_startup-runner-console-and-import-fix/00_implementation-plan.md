# Scheduler Startup Runner and Import Fix

## Objective

Resolve the blank Python console windows left by Windows logon runners and restore the scheduler CLI/TUI when the runtime `run_requests` directory shadows the Python module of the same name.

## Scope

- Register the daemon and elevated worker with `pythonw.exe` when it exists beside the active Python interpreter; keep a fallback for environments without it.
- Keep scheduled task stdout/stderr in scheduler logs and retain the explicitly visible delayed-run test window.
- Configure the existing `Winget Update` task with the same silent and noninteractive flags already used by the separate `Winget Upgrade` task.
- Rename the queue implementation module so a data directory named `run_requests` cannot shadow its import.
- Add focused regression coverage and update user and handoff documentation.
- Investigate the reported PowerShell prompt difference without changing the external profile or unrelated submodule state.

## Acceptance Criteria

1. `scheduler tui` and CLI imports succeed when the existing `modules/scheduler/run_requests/` data directory is present.
2. Generated Windows runner registration uses windowless Python when available and falls back safely when it is absent.
3. The delayed runner test still opens a visible task console.
4. Focused scheduler tests, lint, CLI help, and diff checks pass.
5. Documentation explains how to update already-installed runner actions and where scheduled task output is available.
6. PowerShell prompt findings and any limit on restoring the configured theme are recorded clearly.

## State Preservation

Do not move, delete, or rewrite files in the existing `run_requests/` runtime directory. A `.running` request may refer to work already claimed by a worker.

## Approval and Publication

No commit or push is authorized. User manual validation of the updated Windows runner remains necessary because tests must not modify Task Scheduler registrations.
