# Runtime Lifecycle Module Plan Status

## Objective

Implement the V3 plan for a reusable Windows task lifecycle package and migrate `snips` as its first consumer.

## Current State

- The user-provided V3 is the main plan at `docs/plans/20261119-runtime-lifecycle-module/plan.md` in this worktree.
- Branch: `codex/startup-lifecycle-20261119` (uncommitted and unpushed; ready for authorized commit and integration into `main`).
- Worktree: `C:\Users\mcarls\src\scripts\.worktrees\startup-lifecycle-20261119`.
- Integration target: `main` (`HEAD` and `merge-base` at `e7b9f36d`; zero divergence, no merge conflicts).
- Final code and integration review completed with no material defects found.
- Interactive hotkey acceptance (`Ctrl+Alt+V`, `Ctrl+Alt+B`) is **Passed** via direct user verification in the Windows desktop.
- Fresh Windows login acceptance remains **Pending** until observed after a normal Windows sign-in.

## Acceptance Matrix

| Criterion | Status | Evidence / Notes |
| --- | --- | --- |
| `Ctrl+Alt+V` Markdown fenced clipboard paste | **Passed (manual user verification)** | Directly verified by the user in an interactive Windows desktop. (Earlier agent `SendInput` attempt failed with Win32 `ERROR_ACCESS_DENIED (5)` due to agent sandbox/UIPI restriction, not a `snips` defect.) |
| `Ctrl+Alt+B` Markdown code-block template | **Passed (manual user verification)** | Directly verified by the user in an interactive Windows desktop. |
| Task Scheduler registration & `Run\Snips` migration | **Passed** | `snips startup apply --apply` registered `\Scripts\snips-runtime` (`Ready`, `enabled: true`), removed only `HKCU\...\Run\Snips` after verification, and `snips doctor --json` reports `ok: true`. |
| Watchdog idempotency, recovery, and `disable`/`enable`/`stop` | **Passed** | `snips ensure-runtime --apply --quiet` twice preserved PID; stopping AutoHotkey recovered PID `14280 -> 34748` (`06:58:01`) and `34748 -> 53796` (`07:00:01`) with `0x00000000`; `disable` paused recovery past `06:59:00`; ongoing ticks succeed (`07:20:01`, `0x00000000`). |
| Automated unit, lint, format, compile, and diff checks | **Passed** | `runtime_lifecycle`: 58 passed; `snips`: 35 passed, 0 skipped (including `AutoHotkey64.exe /validate`); `scripts_help`: 55 passed; Ruff format/lint, `compileall`, and `git diff --check` passed. |
| Fresh Windows login startup (`LogonTrigger`) | **Pending — not tested** | Registered XML contains enabled `<LogonTrigger>` (`Delay=PT5S`, `UserId=XERES\mcarls`), `InteractiveToken`/`LeastPrivilege`, `MultipleInstancesPolicy=IgnoreNew`, and valid `pythonw.exe` paths; active user session was not signed out or rebooted. |

## Post-Login Verification Procedure (Pending)

On your next normal Windows sign-in:
1. Wait ~10 seconds without manually launching `snips`.
2. Confirm one `AutoHotkey64.exe` process is running `C:\Users\mcarls\AppData\Local\snips\runtime\snips.ahk` (no duplicates).
3. Run `snips status --json` and `snips doctor --json`; confirm `runtime.running: true`, `startup.task.last_result: 0`, and `ok: true`.
4. Correlate `startup.task.last_run` (and Task Scheduler Operational history / `%LOCALAPPDATA%\snips\runtime\lifecycle.log`) with the Windows logon timestamp to distinguish logon-trigger execution from periodic 1-minute recovery.
5. Verify `Ctrl+Alt+V` remains functional.

## Final Validation

- `python -m ruff format --check --line-length 120 modules/runtime_lifecycle modules/snips` — passed (21 files).
- `python -m ruff check modules/runtime_lifecycle modules/snips` — passed.
- `python -m compileall -q modules/runtime_lifecycle/runtime_lifecycle modules/snips/snips` — passed.
- `python -m pytest -q --basetemp=modules/runtime_lifecycle/.pytest_tmp_root modules/runtime_lifecycle/tests` — 58 passed.
- `python -m pytest -q --basetemp=modules/snips/.pytest_tmp_root modules/snips/tests` — 35 passed (0 skipped).
- `python -m pytest -q --basetemp=modules/scripts_help/.pytest_tmp_root modules/scripts_help/tests` — 55 passed.
- `git diff --check` — passed.
