# Status

Stages 1 through 4 are implemented and validated. Stages 5 and 6 preserve schedule task order and ensure only Admin tasks run elevated; implementation and validation are pending.

## Verification

- `Invoke-Tests.ps1 -Target scheduler -SkipBootstrap` — passed; compile and CLI help checks passed, 63 tests passed, and the generated registration PowerShell parsed successfully.
- `.venv/Scripts/python.exe -m ruff check modules/scheduler` — passed.
- `.venv/Scripts/python.exe -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e modules/scheduler` — editable install updated to scheduler 0.2.0.
- From `modules/scheduler`, `..\..\.venv\Scripts\python.exe -c "import scheduler; print(scheduler.__version__)"` — printed `0.2.0`.
- Both installed `scheduler.exe` and `sched.exe` entry points expose `setup windows-runner --help`.
- `git diff --check` — passed.
- Windows-only PowerShell parser and registration-configuration check is included in the scheduler validation target; it creates no scheduled task.
- Read-only CLI status query `python -m scheduler.cli setup windows-runner status` returned `{"installed": false}`.

## Stage 2 Progress

- Plan recorded in `02_setup-gate__planned.md`.
- Readiness helper uses `cross_platform.SystemUtils` and validates that the runner is installed, enabled, highest-privilege, interactive, and launches the daemon.
- CLI warns in red before global or subcommand help when setup is incomplete, blocks normal operations, and leaves setup commands available. `scheduler setup windows` installs directly; `windows-runner` remains an alias.
- TUI displays a bold red setup banner with only setup selectable until readiness succeeds. It rechecks setup when returning to the main menu.
- Linux setup was not implemented; unsupported systems receive an explanatory warning.

### Stage 2 Verification

- `./Invoke-Tests.ps1 -Target scheduler -SkipBootstrap` — passed: compile, CLI help, 73 pytest tests, Windows PowerShell parser check, and report generation.
- `.venv/Scripts/python.exe -m ruff check modules/scheduler/scheduler modules/scheduler/tests modules/scripts_help/scripts_help/registry/registry.py` — passed.
- `.venv/Scripts/python.exe -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e modules/scheduler` — passed; editable package is scheduler 0.3.0.
- `git diff --check` — passed.
- The first dispatcher attempt could not create its isolated temporary directory under the current sandbox permissions. The final dispatcher run used the command runner's elevated sandbox for isolated validation only; no live Windows scheduled task was registered or modified.

## Stage 3: Setup Capture and Runtime Diagnostics

- The user observed `Permission denied` reading the elevated setup helper's `stdout.txt`. The task file on disk proves registration completed despite the TUI displaying setup failure.
- Elevated stdout/stderr files are now created by the unelevated caller before launching the UAC process. Capture read failures fall back to the launcher output while preserving the elevated child's exit code.
- Runner status maps only PowerShell `ObjectNotFound` to `installed=false`; other errors now propagate into the existing “Could not verify” fail-closed readiness state.
- Read-only task XML shows the task is enabled for `XERES\mcarls`, `InteractiveToken`, `HighestAvailable`, and invokes the expected Python executable/config with `daemon --interval 30`.
- The task XML's `LastTaskResult=267011` (`0x41303`) and 1999 sentinel LastRunTime indicate the Windows runner has not run. The task output log contains only the initial manual run on 2026-09-26; that run failed in the old PowerShell UAC child ExitCode race, before the executor fix. The system log later records a `TASK_START` at 2026-10-08 23:35:46 from an interactive manual run, with no corresponding completed run log at inspection time.
- `scheduler_data.json` enables `EveryOtherDay` on Monday/Wednesday/Friday at 13:00. It is a three-days-per-week schedule, not a daily/every-other-calendar-day schedule. Since the runner never ran, no later recurrence could have been processed.
- Task Scheduler Operational history is disabled, so no additional event history is available. The live task was not started, reinstalled, or removed.

### Stage 3 Verification

- `./Invoke-Tests.ps1 -Target scheduler -SkipBootstrap` — passed: compile, CLI help, 74 pytest tests, Windows PowerShell parser check, and report generation.
- `.venv/Scripts/python.exe -m ruff check modules/scheduler/scheduler/windows_task.py modules/scheduler/tests/test_windows_task.py` — passed.
- `git diff --check` — passed.
- The default sandbox could not create the dispatcher's isolated temp root. The same validation command passed using the command runner's elevated sandbox; it did not touch the live task.

## Stage 4: Delayed Elevated Runner Test from the TUI

- Plan recorded in `04_tui_delayed_runner_test__planned.md`.
- Added an atomic file-backed one-shot queue separate from `scheduler_data.json`; the daemon polls requests each second while schedule evaluation keeps its configured interval.
- The TUI now offers immediate manual run or delayed elevated runner test for Admin tasks. The delayed option requires an installed, Running runner, queues for about ten seconds later, and returns immediately.
- The daemon launches queued work in a visible Windows console. The executor refuses a per-run UAC fallback if an Admin request somehow reaches a non-elevated daemon.
- `.\Invoke-Tests.ps1 -Target scheduler -SkipBootstrap` — passed: compile, CLI help, 85 pytest tests, Windows PowerShell parser check, and report generation.
- `.venv/Scripts/python.exe -m ruff check modules/scheduler/scheduler modules/scheduler/tests modules/scripts_help/scripts_help/registry/registry.py` — passed.
- `git diff --check` — passed.
- Tests mock task execution and runner state; no live Winget command or Task Scheduler entry was run or modified.

## Stage 5: Preserve Schedule Assignment Order

- Plan recorded in `05_schedule_task_order__planned.md`.
- Schedule execution is already synchronous; attached tasks currently come from an alphabetically sorted listing. Stage 5 persists attachment order and uses it for execution.
- Implementation and validation pending.

## Stage 6: Honor Per-Task Privilege Flags

- Plan recorded in `06_task_privilege_isolation__planned.md`.
- The current single highest-privilege daemon would also elevate tasks with `admin=False`; setup must be split into a Limited schedule daemon and a Highest Admin worker.
- Updating the existing one-task runner requires running `scheduler setup windows` again and approving UAC once for the worker registration. Normal scheduled executions will not request UAC.
- Implementation and validation pending.

## Risks and Limits

- The runner is configured for the launching user's interactive logon and stops at sign-out. This preserves access to user-scoped `winget` state.
- Registering or updating the task requests UAC elevation once. Automated tests mock PowerShell and do not modify the live Task Scheduler registry.
- Manual start can execute due/catch-up tasks and is guarded by confirmation.
- Registration readiness confirms task configuration only, not runtime success. A last-run timestamp/result is needed to establish that the daemon has executed.
- The live task was only inspected read-only during Stage 3; it was not started, reinstalled, or removed.
