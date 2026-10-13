# Stage 1: Runner Visibility and Import Collision

## Planned Changes

- Select `pythonw.exe` for Windows background runner actions when present.
- Move the queue implementation to a module name that cannot collide with `run_requests/` data.
- Apply the existing Winget Upgrade task's silent and noninteractive flags to the scheduled Winget Update task.
- Add regression tests for executable selection and queue behavior.
- Update package version, CLI registry version, README, and handoffs.

## Verification

- Run the scheduler target in `Invoke-Tests.ps1` with bootstrap skipped.
- Confirm `scheduler --help` imports successfully with the current runtime request directory present.
- Run Ruff and `git diff --check` on the changed files.
- Do not register, start, update, or remove live scheduled tasks during automated validation.

## Manual Validation

After reviewing the patch, rerun `scheduler setup windows` to update the existing daemon and Admin worker actions. Confirm the empty runner consoles no longer appear, then use `scheduler tui` → **View Logs** to inspect the next scheduled task output.
