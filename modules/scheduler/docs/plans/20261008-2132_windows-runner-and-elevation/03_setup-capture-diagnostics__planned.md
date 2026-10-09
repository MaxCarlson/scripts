# Stage 3: Setup Capture and Runtime Diagnostics

## Plan

- Fix elevated PowerShell output capture so a successful Task Scheduler registration is not reported as failed just because the unelevated process cannot read a capture file.
- Create output capture files before elevation to preserve the caller's inherited ACL, and tolerate unreadable capture files while preserving the child exit code and outer process output.
- Make runner status distinguish a missing task from inspection errors; fail closed when Windows denies status access instead of reporting the task as absent.
- Keep “registered and configured” separate from “has run”: registration readiness must not claim that the daemon has executed, while status diagnostics expose the task's last-run/result fields.
- Add focused mocked tests and record the current machine evidence without starting, reinstalling, or removing the live task.

## Verification

- Run scheduler validation through `./Invoke-Tests.ps1 -Target scheduler -SkipBootstrap`.
- Run Ruff and `git diff --check`.
- Inspect task XML and module logs read-only. Do not start the task because overdue catch-up work may execute.

## Acceptance Criteria

1. An unreadable elevated stdout/stderr capture does not turn a successful child exit into a setup exception.
2. A real elevation child failure still propagates its exit code and error detail.
3. Status reports not-installed only for an object-not-found result and surfaces other PowerShell errors.
4. Documentation states that successful setup confirms registration/configuration, not a successful daemon run.
