# Runtime Lifecycle Module — Design

## Intent

Create a reusable, zero-dependency Python package for Windows startup and
Scheduled Task management, then migrate `snips` as its first consumer. Later
modules can adopt the shared XML, ownership, status, and control APIs without
changing the core task model.

## Scope

This phase implements `runtime_lifecycle` and migrates only `snips`. The
notifications, scheduler, resource coordinator, backup, and rrbackup modules
keep their existing implementations for incremental future migrations.

## Shared package

- Python 3.10+, no runtime dependencies.
- Immutable `TaskPrincipal`, trigger models, and `TaskSpec`; absolute executable
  and working-directory paths; configurable settings, restart policy, and task
  folder/name.
- Current-user interactive/limited is the default. SYSTEM/service-account and
  highest-privilege modes are represented for future modules and require an
  elevated process for mutations.
- Logon, boot, repeating time, and once/daily/weekly/monthly calendar triggers.
- Canonical Task Scheduler XML is generated and parsed with the standard
  library. The renderer emits UTF-16LE with BOM and Task Scheduler schema
  version 1.3. Parsing normalizes UTF-8/UTF-16 XML into semantic fields.
- Ownership description marker includes manager, owner, name, schema, and
  deterministic SHA-256 spec hash. Preview reports create/update/no-op/conflict;
  status detects hash and semantic drift, including manual GUI edits.
- Mutations fail closed for unmarked, foreign-owner, or different-principal
  tasks. `force` applies only to replacement; removal always requires verified
  ownership.
- API and CLI support preview, apply, status, list, enable, disable, start,
  stop, remove, snapshot, and restore. Status includes Scheduler state, enabled
  flag, principal, paths, last/next run, missed runs, raw result, decoded
  HRESULT, and path health. List audits managed tasks across owners.
- A named `Local\\` mutex handles cross-process serialization, including
  abandoned locks. Non-Windows callers use a file-lock fallback. Helpers locate
  `pythonw.exe` and spawn detached child processes with conditional job
  breakaway.

## `snips` consumer

- Add hidden `snips ensure-runtime`, with dry-run default and an explicit apply
  flag. A per-user task runs a `pythonw.exe` action at logon and every minute.
- The ensure command uses a named mutex and checks the runtime PID, process
  image, and build ID before launch. A healthy matching PID is left untouched;
  only recovery transitions and errors are logged, without clipboard or
  snippet data. Healthy and recovered checks return success; failures return a
  nonzero code.
- AutoHotkey uses detached process flags, with a safe breakaway fallback and
  live child-survival verification. Keep `#SingleInstance Force` because the
  existing explicit reload path relies on it; serialized health checks avoid
  unnecessary replacement.
- `snips startup` exposes preview/apply/status/enable/disable/start/stop/remove.
  Stop/disable describe Scheduler action state and do not imply that a child
  AutoHotkey process was stopped.
- `snips install --apply` registers and verifies the matching owned task before
  removing an exact matching `HKCU\\...\\Run\\Snips` command. Any earlier
  failure leaves the Run value intact. Foreign Run values are never modified.
- `snips status` and `doctor` include registration/drift, Scheduler state,
  decoded last result, path health, and the latest recovery error.

## Design decisions

- Use canonical XML rather than Task Scheduler creation switches, because the
  task definition needs multiple trigger types and explicit settings.
- Explicitly set battery behavior, `IgnoreNew`, start-when-available,
  `InteractiveToken`/`LeastPrivilege` where applicable, hidden state, and task
  execution limits; do not depend on Windows defaults.
- Use a deterministic past `TimeTrigger` start boundary with repetition so the
  watchdog can start after registration without requiring a new logon.
- Preserve AutoHotkey `Force` for explicit config reload; idempotent ensure and
  the mutex prevent routine watchdog checks from replacing a healthy instance.
- `CREATE_BREAKAWAY_FROM_JOB` is conditional on the containing job's policy;
  fallback drops the flag when denied, and final live verification must confirm
  the target process survives task completion.

## Validation and rollout

- Test pure models/XML/parser and mocked Scheduler/registry/process boundaries
  before applying persistent startup changes.
- Preview the exact task and inspect the UTF-16 XML. Apply only after matching
  registration status is confirmed, then verify PID stability, recovery,
  console-free execution, enable/disable, and exact Run-value migration.
- Keep the implementation on its non-main task branch. Do not commit, push, or
  merge without explicit authorization.
