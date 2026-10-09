# Windows Runner and Unattended Elevation Handoff

## Scope

Add Windows Task Scheduler runner setup to CLI and TUI, and support highest-privilege unattended task execution.

## Current State

- Stages 1 through 4 implementation and automated validation are complete. Stages 5 and 6 preserve schedule task order and honor each task's Admin flag; implementation and validation are pending.
- The current PC has a registered, enabled, highest-privilege interactive logon task, but its last-run status indicates that it has never run. Module logs show the initial manual run failed and no daemon runs afterward.
- Stage 3 inspected the task and logs read-only. It did not start, reinstall, or remove the task.
- Stage 4 tests use mocks and isolated request files; no live task was run. The delayed test option requires the installed runner to be in `Running` state and opens a visible console.
- Exact machine evidence and validation commands/results are recorded in `STATUS.md`.

## Next Action

After reviewing overdue catch-up tasks, use `scheduler setup windows start --yes` to start the already registered runner. This may execute catch-up work. Setup readiness means the task is registered and configured; confirm last-run details through `scheduler setup windows status`. The TUI's delayed runner test becomes available while that runner is active. The `windows-runner` alias remains supported. Linux setup is deferred pending explicit user approval.
