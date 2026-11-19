# Runtime Lifecycle Module Implementation Plan (V3)

**Goal:** Build a reusable, zero-dependency Windows user-session and scheduled-task lifecycle package (`runtime_lifecycle`) designed to unify task/startup plumbing across `snips`, `notifications`, `scheduler`, `resource_coordinator`, `backup_module`, and `rrbackup`—starting with `snips` as its first consumer.

**Architecture:** `runtime_lifecycle` owns canonical Task Scheduler XML generation/parsing, principal/SID normalization, dual-layer drift detection, safe CRUD/control/snapshot/restore operations, cross-module task auditing (`list`), CLI, a `Local\` named mutex helper, and a detached process-spawning helper. Consumers own process identity, health checks, and recovery policy. `snips` is migrated in this phase; other modules retain their existing implementations and can migrate incrementally without API changes.

**Spec:** [2026-11-19-runtime-lifecycle-design.md](../../superpowers/specs/2026-11-19-runtime-lifecycle-design.md)

## Constraints

- Zero third-party runtime dependencies; Python 3.10+; 4-space indentation.
- Default principal is current user, `InteractiveToken`, `LeastPrivilege` (no elevation, no Session 0 service). Elevated (`HighestAvailable`) and `SYSTEM` (`ServiceAccount`) principals are supported in the model for future consumers (`notifications` heartbeat, `scheduler` admin worker, `resource_coordinator` boot/logon, `backup_module`/`rrbackup`) and fail closed with `ElevationRequiredError` when called without Administrator privileges.
- Every executable and working directory in a `TaskSpec` must be absolute (and verified to exist when applying live specs).
- Unmarked, foreign-owner, or different-principal tasks are conflicts. `force=True` only authorizes replacement on `apply`; `remove` always refuses unowned tasks.
- `snips` install is preview-first and migrates only the exact owned `HKCU\...\Run\Snips` value *after* task registration and matching status/spec verification succeed.
- Never log snippet contents or clipboard data. Never log healthy no-op `ensure-runtime` ticks.
- Preserve `#SingleInstance Force` in `snips` for explicit reload/update; mutex + health/build checks prevent unnecessary restarts.
- All CLI options across `runtime-lifecycle` and new `snips` commands provide both a single-dash short flag and a double-dash kebab-case long flag (e.g., `-a, --apply`, `-p, --preview`, `-f, --force`, `-j, --json`).
- Keep unrelated task consumers (`notifications`, `scheduler`, `resource_coordinator`, `backup_module`, `rrbackup`) unchanged in this phase. Do not commit, push, or merge without explicit authorization.
- Bump `snips` to `0.2.0` and keep version sources synchronized.

## File Map

- Create `modules/runtime_lifecycle/` package, CLI entry point (`runtime-lifecycle`), README, and unit tests under `modules/runtime_lifecycle/tests/`.
- Update `modules/snips/snips/`, its tests, `pyproject.toml`, and README.
- Update repo module help registry for the `runtime-lifecycle` CLI.
- Maintain this plan's `STATUS.md` and `checklist.md` during execution.

---

## Task 1: Task Model, Principal/SID Normalization, Triggers, and Canonical XML

- Define validated, immutable dataclasses:
  - `TaskPrincipal`:
    - `mode`: `"current_user"` (default) | `"system_service"` (`S-1-5-18`)
    - `logon_type`: `"interactive"` (default) | `"service_account"`
    - `run_level`: `"limited"` (default) | `"highest"`
    - `sid`: resolved Windows SID (auto-resolved via zero-dependency `ctypes` `advapi32` or `whoami /user` for current user; `S-1-5-18` for `system_service`).
  - Trigger models (any non-empty combination allowed):
    - `LogonTrigger(delay: str | None = "PT5S", user_id: str | None = None)`
    - `BootTrigger(delay: str | None = None)`
    - `RepeatingIntervalTrigger(interval: str, start_boundary: str = "2020-01-01T00:00:00", duration: str | None = None)` — rendered as `<TimeTrigger>` with deterministic `<StartBoundary>` so repetition activates immediately upon registration without requiring a logout/logon cycle.
    - `CalendarTrigger(schedule: Literal["once", "daily", "weekly", "monthly"], start_time: str = "02:00", interval: int = 1, days_of_week: tuple[str, ...] = (), days_of_month: tuple[int, ...] = (), months: tuple[int, ...] = (), start_date: str = "2020-01-01")` — supports `backup_module` / `rrbackup` schedules.
  - `TaskSpec`:
    - `owner`, `name`, `executable`, `args`, `working_dir`, `triggers`, `principal=TaskPrincipal.current_user_limited()`, `folder="\\Scripts"`, `task_name_override: str | None = None` (defaults to `\\Scripts\\<owner>-<name>`), `hidden=True`, `execution_time_limit="PT2M"` (`"PT0S"` for unlimited daemons), `multiple_instances="IgnoreNew"`, `allow_on_battery=True`, `start_when_available=True`, `wake_to_run=False`, `restart_count=0`, `restart_interval="PT1M"`.
  - Result & error models: `PreviewResult`, `ApplyResult`, `TaskStatus`, `TaskSummary`, `TaskSnapshot`, `OwnershipConflictError`, `ElevationRequiredError`, `UnsupportedPlatformError`, `TaskBackendError`.
- Render deterministic canonical XML via `xml.etree.ElementTree`:
  - Encode as **UTF-16LE with BOM** (`<?xml version="1.0" encoding="UTF-16"?>`) for Windows Task Scheduler compatibility.
  - Explicitly emit `<LogonType>`, `<RunLevel>`, `<UserId>` (normalized SID), `<DisallowStartIfOnBatteries>`, `<StopIfGoingOnBatteries>`, `<MultipleInstancesPolicy>`, `<StartWhenAvailable>`, `<WakeToRun>`, `<Hidden>`, `<ExecutionTimeLimit>`, and optional `<RestartOnFailure><Interval>...</Interval><Count>...</Count></RestartOnFailure>`.
  - Embed structured ownership metadata in `<Description>`:
    `managed-by=runtime_lifecycle; owner=<owner>; name=<name>; schema=1; spec_hash=<sha256>`
- Implement a **canonical XML parser** (supporting UTF-16 and UTF-8) that extracts ownership metadata and normalized semantic fields (`principal_sid`, `logon_type`, `run_level`, `executable`, `arguments`, `working_dir`, `triggers`, `settings`, `enabled`) from Windows-exported XML, plus a clean semantic diff for `preview`.
- **Tests:** XML shape, UTF-16LE encoding/escaping, all trigger types (logon, boot, deterministic `TimeTrigger` repetition, daily/weekly/monthly/once calendar, combined logon+interval), `RestartOnFailure` emission, principal/SID normalization, field/path validation, hash determinism, and semantic XML round-trip parsing.

---

## Task 2: Safe Lifecycle Operations, Snapshot/Restore, Audit, Helpers, CLI, and Mutex

- Implement Windows backend using argument-array `subprocess.run` calls (`schtasks.exe`) and secure temporary UTF-16LE XML files (always cleaned up in `finally`); create target folder (e.g. `\Scripts`) as needed.
- Implement core lifecycle operations:
  - `is_elevated() -> bool` (`ctypes.windll.shell32.IsUserAnAdmin()`). Refuse `highest` or `system_service` mutations with `ElevationRequiredError` when not elevated.
  - `preview(spec) -> PreviewResult`: returns planned action (`create` | `update` | `noop` | `conflict`), canonical XML, and semantic diff.
  - `apply(spec, force=False) -> ApplyResult`: enforces ownership & principal checks before mutation; idempotent on matching spec.
  - `status(owner, name, spec=None, folder="\\Scripts", task_name_override=None) -> TaskStatus`:
    - Registration state: `registered` | `missing` | `drifted` | `conflict`
    - Scheduler state: `Ready` | `Running` | `Disabled` | `Queued` | `Unknown`
    - Parsed definition metadata: `enabled`, `principal_sid`, `logon_type`, `run_level`, `logged_off_capable`, `executable`, `arguments`, `working_dir`
    - Runtime metadata: `last_run`, `next_run`, `missed_runs`, raw `last_result`, **decoded HRESULT** (masking signed 32-bit ints with `& 0xFFFFFFFF`), and path health (`executable_exists`, `working_dir_exists`).
  - **Dual-layer drift detection:** flag `drifted` if *either* `spec_hash` differs *or* parsed live XML semantic fields diverge from `spec` (catches manual Task Scheduler GUI edits).
  - `enable` / `disable` / `start` / `stop` / `remove`: all verify ownership marker + principal SID before mutating; `remove` always refuses unowned tasks regardless of flags.
  - `snapshot(owner, name, ...) -> TaskSnapshot` and `restore(snapshot) -> ApplyResult`: captures exact raw XML + `enabled` + `sha256` and restores only verified `runtime_lifecycle`-owned snapshots (enabling safe transactional upgrades for `resource_coordinator` and future consumers).
  - `list_tasks(owner=None, folder="\\Scripts") -> list[TaskSummary]`: enumerates managed tasks, reporting owner, state, last result, `logged_off_capable`, and stale/missing executable path flags.
- Shared process & concurrency helpers (zero-dependency):
  - `resolve_pythonw(executable: Path | None = None) -> Path`: checks sibling `pythonw.exe`, falls back to `Path(sys.base_prefix) / "pythonw.exe"` for minimal venvs, and fails fast if unavailable.
  - `spawn_detached(argv, *, cwd, env=None, hidden=True, breakaway=True) -> subprocess.Popen`: uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB` (with safe fallback dropping `CREATE_BREAKAWAY_FROM_JOB` if denied), `stdin=DEVNULL`, `stdout=DEVNULL`, `stderr=DEVNULL`, `close_fds=True`.
  - `NamedMutex(name, *, timeout_seconds=5.0, owner_metadata_path=None)`: uses `Local\<name>` via `ctypes.WinDLL("kernel32", use_last_error=True)`, handles `WAIT_ABANDONED` (`0x00000080`) as acquired ownership, optionally records PID/timestamp metadata, and provides a safe file-lock fallback on non-Windows.
- Implement `runtime-lifecycle` CLI (`preview`, `apply`, `status`, `list`, `enable`, `disable`, `start`, `stop`, `remove`) with short/long option pairs, `-j, --json` output, and preview-first defaults for mutating actions.
- **Tests:** Mocked backend CRUD, idempotence, dual-layer drift (spec change + simulated GUI edit), foreign/unmarked/wrong-SID conflicts, `force` scope (`apply` only, never `remove`), `ElevationRequiredError` gating, `snapshot`/`restore` hash verification, signed-to-unsigned HRESULT decoding, `list_tasks`, `resolve_pythonw` fallback, `spawn_detached` breakaway fallback, tempfile cleanup on error, and mutex contention + `WAIT_ABANDONED` handling.

---

## Task 3: `snips` Watchdog, Detached Launcher, and Safe Migration

- Add `snips ensure-runtime` with dry-run default and `-a, --apply`:
  - Acquires `NamedMutex("snips-runtime-ensure")` before inspecting or launching.
  - Validates existing AutoHotkey process identity and script/build match before launching; leaves a healthy matching process untouched.
  - Quiet on healthy no-op ticks; writes state transitions (started/recovered) and failures to a bounded log file (no snippet or clipboard data) so `pythonw.exe` failures are diagnosable.
  - Returns exit code `0` for both "already healthy" and "successfully recovered", and non-zero only on failed recovery.
- Register the `snips` task via `runtime_lifecycle`:
  - `owner="snips"`, `name="runtime"` (`\Scripts\snips-runtime`), default `TaskPrincipal.current_user_limited()`.
  - Triggers: `LogonTrigger(delay="PT5S")` + `RepeatingIntervalTrigger(interval="PT1M")` (configurable via `-i, --interval`).
  - Action: `resolve_pythonw()`, explicit absolute `working_dir`, args `["-m", "snips.cli", "ensure-runtime", "--apply"]` (plus `--config` if non-default).
  - Settings: `hidden=True`, `execution_time_limit="PT2M"`, `multiple_instances="IgnoreNew"`, `allow_on_battery=True`.
- Launch `AutoHotkey.exe` using `runtime_lifecycle.spawn_detached(...)` and verify child process stays alive past a short startup window before reporting recovery success.
- Preserve `#SingleInstance Force` in `snips.ahk` for explicit reload/update; ensure normal recovery never invokes a healthy script twice.
- Add `snips` task lifecycle CLI commands (`preview`, `apply`, `status`, `enable`, `disable`, `start`, `stop`, `remove`) with short/long flags, and surface Scheduled Task state, decoded last result, and last recovery log error in `snips status` and `snips doctor`.
- Safe HKCU Run migration:
  1. Register `\Scripts\snips-runtime` via `runtime_lifecycle.apply(...)`.
  2. Call `runtime_lifecycle.status(...)` and verify `registered` + matching spec.
  3. Only then remove the exact `snips`-owned `HKCU\...\Run\Snips` value. Leave the registry untouched on any earlier failure, and never touch foreign Run values.
- Bump `snips` to `0.2.0`, keep all version sources synchronized, add `runtime-lifecycle` dependency, and update README and repo module help registry.
- **Tests:** `ensure-runtime` no-op/start/failure/build-mismatch, generated task args include `--apply`, `pythonw.exe` resolution/fallback, detached launch + breakaway fallback, migration ordering and rollback on failure, foreign Run value preservation, bounded error logging, and CLI status/doctor output.

---

## Task 4: Focused Validation and Live User-Session Setup

- Run focused `runtime_lifecycle` and `snips` test suites, Ruff lint/format checks, and dependency-order validation.
- Run `snips` task `preview` and inspect the generated UTF-16LE XML (verifying SID, two-trigger logon + `TimeTrigger` repetition, battery flags, `IgnoreNew`, `Hidden`, absolute `pythonw.exe`, and `--apply`).
- Apply from the task branch's installed packages:
  1. Confirm `runtime-lifecycle list` and `snips status` show `\Scripts\snips-runtime` as `registered`, `Ready`, with a valid `Next Run Time` (confirming repetition is active without needing a reboot).
  2. Confirm repeated `ensure-runtime --apply` leaves the running `AutoHotkey.exe` PID unchanged.
  3. Kill `snips.ahk` manually and verify the next scheduled tick restores it automatically with zero console window flash.
  4. Verify `disable` pauses recovery, `enable` resumes it, and `stop`/`disable` clearly reports task state without falsely claiming `AutoHotkey.exe` was terminated.
  5. Verify the old `HKCU\...\Run\Snips` entry was cleanly migrated.
- Review `git diff --check`, task-only diff, and final branch status. Do not commit, push, or merge.

---

## Future Incremental Migration Roadmap (Post-Phase 1)

Once `runtime_lifecycle` is proven on `snips`, existing consumers can migrate one at a time with zero changes to `runtime_lifecycle`'s core model:
1. **`notifications`** (4 tasks: outbox, coordinator observer, toast helper, host heartbeat — including `--headless` SYSTEM mode).
2. **`scheduler`** (2 logon tasks: limited daemon + elevated admin worker, plus `readiness.py` inspection).
3. **`backup_module` & `rrbackup`** (calendar triggers + `HighestAvailable` + `WakeToRun`).
4. **`resource_coordinator`** (boot/logon/viewer tasks + `snapshot`/`restore` transactional upgrade integration).

