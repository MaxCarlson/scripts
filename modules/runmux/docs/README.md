# Runmux Engineering Guide

Last updated: 2026-06-22 06:44:27 -07:00

This directory is the one-stop engineering introduction and handoff space for
`runmux`. It explains what the program is, how it is built, its important
terminal/process constraints, active implementation plans, and how LLM-driven work must
be planned, verified, staged, approved, and resumed.

Before working:

1. Read applicable global and repository-level LLM instructions.
2. Read [`HANDOFF.md`](HANDOFF.md) for exact current state and next action.
3. Read [`plans/HANDOFF.md`](plans/HANDOFF.md) to find the latest active plan.
4. Read that dated plan folder's `HANDOFF.md`, `STATUS.md`, `checklist.md`,
   implementation plan, and current stage plan.
5. Inspect the source, tests, worktree, and recent commits.

Information flows from general to specific:

- Global/repository LLM instructions: generic workflow rules.
- This README: runmux purpose, architecture, behavior, commands, and document
  map.
- Root `HANDOFF.md`: immediate runmux worktree and resume state.
- `plans/HANDOFF.md`: identifies the latest active or recently completed plan.
- Dated plan folder: plan-specific requirements, checklist, status, and handoff.

Optional project-wide future planning uses:

- `plans/master_plan.md`: long-term future plan for runmux as a whole.
- `plans/master_plan_checklist.md`: tracks completion of entire dated
  folder-level implementation plans.

These files are currently optional and need not exist. Detailed stages and
features remain inside their dated plan folders.

Do not select a plan from its folder timestamp alone. Confirm the candidate from
`plans/HANDOFF.md` using its status/checklist, file timestamps, the staged
worktree, and recent commits limited to `modules/runmux/`.

## Project Overview

`runmux` is a cross-platform terminal process manager and multiplexer. It starts
programs under detached supervisor processes, records shared metadata, preserves
ANSI terminal output, and lets independent PowerShell or Unix shell sessions
list, view, interact with, monitor, restart, duplicate, pause, kill, and remove
managed runs.

The user-facing goal is similar to the program-management portion of tmux:

- A managed program continues after the launching shell detaches.
- Any later shell can discover it through `runmux ls` or `runmux list`.
- Multiple terminals can view the same output.
- Interactive terminal programs run through a PTY/ConPTY where available.
- Run metadata and command history survive individual shell sessions.
- Full-screen and in-place-rendered programs retain ANSI color and cursor
  behavior as faithfully as the host terminal permits.

Runmux is especially intended for long-running Python CLIs and TUIs such as
`ytaedl`, `video-dedupe`, and `file-util ls`.

## Current Capabilities

- `runmux run PROGRAM ...` starts a supervised program and normally attaches
  interactively.
- `-D/--detach` starts and returns to the shell.
- `-w/--view` or `-a/--attach` starts in view-only mode.
- `runmux list` provides a live selectable list.
- `runmux ls` prints a one-shot list.
- `runmux view -i ID` follows ANSI output without forwarding ordinary keys.
- `runmux interact -i ID` follows output and forwards program input.
- `runmux kill`, `restart`, `duplicate`, `pause`, `resume`, `rm`, and
  `remove-finished` manage lifecycle.
- `runmux stats` shows live process-tree resource information.
- `runmux history`, `save`, and `cmd` provide command history and saved commands.
- Numeric IDs start at zero and removed IDs are reused.
- Working directory and terminal dimensions default to the launching shell.
- Detached Windows supervisors and children are created without visible blank
  console windows.

## Architecture

### CLI

`src/runmux/cli.py` owns argparse definitions and top-level command handlers.
The `runmux` entry point is `runmux.cli:main`.

### Registry

`src/runmux/store.py` owns the SQLite registry. The normal state directory is:

- Windows: `%LOCALAPPDATA%\runmux`
- Unix-like systems: `$XDG_STATE_HOME/runmux` or `~/.local/state/runmux`
- Tests or isolated commands: `--state-dir PATH`

The registry uses WAL mode and stores runs, process identifiers, supervisor IPC
ports, terminal dimensions, status, timing, commands, and attachment sessions.

### Supervisor

Each managed run has a detached `python -m runmux.supervisor` process. It:

- Launches the child under ConPTY/pywinpty on Windows when available.
- Uses a PTY on Unix-like systems.
- Falls back to pipe capture when Windows PTY startup fails.
- Pumps child output into a byte-preserving `output.ansi` file.
- Exposes authenticated localhost TCP IPC.
- Owns process input, resize, status, kill, pause, and resume operations.

The supervisor must remain alive for interaction. Closing or killing the
supervisor makes the managed run unavailable even if stale registry data exists.

### Clients

`src/runmux/client.py` implements list, view, and interact behavior.

- Output clients tail the shared ANSI log.
- Interact clients open an authenticated input socket.
- Ctrl-X is the runmux command prefix in interact mode.
- View and interact attachments have unique session IDs and heartbeat leases.
- The supervisor, not a client, is authoritative for input ownership.

### History

The current implementation stores history and saved commands under
`modules/runmux/.runmux/commands.json`. The active implementation plan will migrate this to
locked JSONL history, separate saved commands, configuration, retention, search,
and summaries.

## Terminal and Process Intricacies

Runmux deals with terminal byte streams, not logical UI widgets. Important
constraints:

- ANSI output may be split across arbitrary read chunks.
- Full-screen TUIs emit cursor movement, screen clears, alternate-screen
  switches, scroll regions, terminal queries, and in-place redraws.
- Logs must remain raw; runmux-specific status UI must only affect attached
  clients.
- Windows special keys arrive through `msvcrt` and must be translated to ANSI
  sequences before forwarding.
- Enter is a carriage return on Windows.
- Terminal dimensions must be sent to the managed PTY.
- Client exit paths must restore cursor visibility and terminal modes.
- Heartbeat leases recover from abruptly closed terminal windows.
- Multiple interact clients require supervisor-controlled serialization; client
  assumptions are insufficient.
- `Ctrl+Shift+X` is not portable because terminals generally encode it the same
  as `Ctrl+X`.

## Active Implementation Plan

The current implementation plan is
[`plans/20260622-0551_runmux-multi-attach-input-lock-history/00_implementation-plan.md`](plans/20260622-0551_runmux-multi-attach-input-lock-history/00_implementation-plan.md).

This is the implementation plan for one set of features. It is not the
ultimate end goal or complete permanent roadmap for runmux.

Stages:

1. Startup readiness: implemented and committed.
2. Multi-attach and FIFO input ownership: implemented, committed, and manually approved.
3. Attachment status UI and persistent settings: partially implemented;
   persistent configuration remains.
4. History search, replay, interactive/fzf selection, and summaries: detailed
   plan updated; implementation pending.

Immediate plan status is in
[`STATUS.md`](plans/20260622-0551_runmux-multi-attach-input-lock-history/STATUS.md).
Feature-level state and stage completion times are in
[`checklist.md`](plans/20260622-0551_runmux-multi-attach-input-lock-history/checklist.md).

## Planning Documents

Each implementation plan too large for one safe cycle gets a dated folder:

```text
docs/plans/YYYYMMDD-HHMM_<descriptive-plan-name>/
```

It contains:

- `00_implementation-plan.md`: complete intended result of this feature set.
- Numbered stage plans: ordered implementation/commit boundaries.
- `STATUS.md`: current operational state.
- `HANDOFF.md`: implementation-plan-specific resume guidance.
- `checklist.md`: stage completion ledger and feature implementation/test state.

Each dated implementation plan uses a branch named from the plan followed by its
creation timestamp. It is merged only after the user validates the completed
program and approves the merge.

Every `docs/` directory and planning subdirectory contains a `HANDOFF.md`.
It may link to more authoritative documents, but it must tell an unfamiliar LLM
what the folder contains, what is current, and what to read next.

Master plans and stage plans end with a local-time `Last edited` timestamp.

Canonical repository plans also live under `plans/modules/runmux/` because that
is required by `MODULE_STANDARDS.md`.

## Cycle Workflow

1. Plan the stage.
2. Populate the stage section in the active plan folder's `checklist.md`.
3. Implement features individually.
4. Mark each feature implemented but not fully tested immediately after coding.
5. Run the previously passing suite.
6. Add focused tests.
7. Run old and new tests together.
8. Promote the stage to implemented and tested.
9. Run Ruff, Black check, compileall, coverage, and smoke checks.
10. Review and document the diff.
11. Stage, but do not commit.
12. Stop for user manual testing.
13. Commit only after explicit approval.
14. Begin the next stage only after the approved commit.

The user may explicitly authorize continuous stage execution. That skips the
pause between stages, but not stage planning, tests, documentation, or commits.

The proposed generic rules being reviewed for global adoption are available in
[`GLOBAL_LLM_DOCUMENTATION_INSTRUCTIONS.md`](GLOBAL_LLM_DOCUMENTATION_INSTRUCTIONS.md).

## Verification Commands

From the repository root:

```powershell
pytest --tb=short -q .\modules\runmux\
ruff check modules\runmux modules\scripts_help\scripts_help\registry\registry.py
black --check --line-length 120 modules\runmux
python -m compileall -q modules\runmux\src\runmux
pytest --cov=runmux --cov-report=term-missing -q .\modules\runmux\
```

Use module-local state for smoke tests:

```powershell
runmux --state-dir modules\runmux\.pytest_tmp_root\smoke run --detach -- python -c "import time; time.sleep(30)"
runmux --state-dir modules\runmux\.pytest_tmp_root\smoke ls
runmux --state-dir modules\runmux\.pytest_tmp_root\smoke interact -i 0
```

## Documentation Responsibilities

- Update this README somewhat at every cycle close.
- Update it comprehensively when a full implementation plan is completed or the
  architecture/public behavior changes materially.
- Update `HANDOFF.md` whenever current work, known risks, staged state, or next
  action changes.
- Update the active plan's `STATUS.md` and `checklist.md` throughout
  implementation.
- Keep global/repository LLM instructions stable and generalized;
  project-specific live details belong in `HANDOFF.md`.
- Do not force incoming LLMs to reconstruct intent exclusively from source code.

The desired handoff is that the user can tell a new LLM only: read the
repository instructions and the runmux docs, inspect the worktree, and continue.
