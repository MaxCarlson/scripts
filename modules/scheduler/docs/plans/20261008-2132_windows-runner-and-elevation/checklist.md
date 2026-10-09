# Checklist

- [x] Add Windows Task Scheduler install/status/start/remove integration.
- [x] Integrate runner lifecycle into CLI setup commands.
- [x] Integrate runner lifecycle into TUI configuration.
- [x] Avoid repeated UAC prompts for already elevated task execution and preserve child exit status.
- [x] Add isolated tests for setup, CLI, TUI, and elevation behavior.
- [x] Update README, package version, scripts-help registry, and handoffs.
- [x] Run focused and full scheduler validation; record exact results.
- [x] Confirm no live task or unrelated machine state was changed.

## Stage 2: Setup Gate

- [x] Add current-OS and Windows runner readiness detection.
- [x] Gate normal CLI operations and warn before CLI help output.
- [x] Add the `setup windows` install shortcut while preserving `windows-runner` compatibility.
- [x] Show a red setup-only menu in the TUI until setup completes.
- [x] Add readiness, CLI, and TUI regression tests without touching the live task.
- [x] Update documentation, version, and handoffs.
- [x] Update validation target, run tests, Ruff, and diff checks.
- [x] Run and record targeted scheduler validation, Ruff, and diff checks.
- [x] Confirm Linux setup remains out of scope and unimplemented.

## Stage 3: Setup Capture and Runtime Diagnostics

- [x] Preserve caller access to elevated output capture files and tolerate capture-read denial after child success.
- [x] Distinguish a missing runner from access/inspection errors in status checks.
- [x] Record the registered task configuration, never-run result, schedule recurrence, and module log evidence.
- [x] Run scheduler validation, Ruff, and diff checks; record exact results.
- [x] Keep live task inspection read-only; do not start or reinstall it.

## Stage 4: Delayed Elevated Runner Test from the TUI

- [x] Add a one-shot file-backed request queue consumed by the daemon.
- [x] Poll one-shot requests without changing normal schedule recurrence timing.
- [x] Run due requests in a visible console through the elevated runner, with no per-run UAC fallback.
- [x] Add immediate and delayed-run choices after selecting a task in the TUI; return immediately after queueing.
- [x] Add isolated tests for request timing, execution routing, visibility/elevation, and TUI behavior.
- [x] Update documentation and handoffs.
- [x] Run scheduler validation, Ruff, and diff checks.
- [x] Confirm no live task was run or Task Scheduler entry modified by tests.

## Stage 5: Preserve Schedule Assignment Order

- [x] Persist and migrate schedule assignment order for attached tasks.
- [x] Append new and reattached tasks after the target schedule's current tasks.
- [x] Verify sequential execution follows assignment order.
- [x] Add storage/service regression tests and update documentation/version.
- [ ] Run scheduler validation, Ruff, and diff checks.

## Stage 6: Honor Per-Task Privilege Flags

- [x] Register a limited scheduler daemon and a separate highest-privilege Admin worker.
- [x] Route scheduled Admin runs through the worker and return results to the scheduler daemon.
- [x] Keep non-Admin scheduled task execution in the limited daemon.
- [x] Update TUI delayed test, readiness, status, start/remove, and setup upgrade handling.
- [x] Add regression tests for privilege routing, UAC avoidance, and sequential result completion.
- [x] Update docs/version.
- [ ] Run scheduler validation, Ruff, and diff checks.
- [x] Ensure tests never modify live Task Scheduler state or execute Winget.
