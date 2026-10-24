# Architecture Assessment

## Current Source Evidence

- Run records are immutable dataclasses with both a reusable numeric ID and a stable full string ID in src/runmux/models.py.
- RunStore.list_runs in src/runmux/store.py reads active, paused, and terminal records without deleting them.
- The list CLI path is unsafe for a workspace browser: listed_records in src/runmux/client.py calls prune_terminal_runs and refresh_active_statuses, which changes the registry. The TUI adapter will query RunStore directly and apply any transient status refresh to display models only.
- Process ownership already lives in runner.py and supervisor.py. Run creation is detached from the launching CLI. kill, pause, resume, restart, and duplicate are API functions.
- client.interact_run owns raw-terminal setup, PTY input, input-lock registration, heartbeats, log following, and detach cleanup. Stage 3 should hand off to it after curses exits, then start curses again.
- Logs are byte-preserving output. client.tail_file reads bytes, while cli_tui.ProcessRunner owns and terminates its subprocess. CliTuiApp.close and PaneWorkspace deletion terminate runners, so these are not safe lifecycle owners for runmux processes.
- cli_tui exposes reusable OutputViewport, ANSI rendering, footer formatting, parser introspection, and form widgets. The current application controller is not a generic external-process host.
- Runmux command history and saved-command JSON use read-modify-write updates in src/runmux/history.py without cross-process locking. history_path_for_state_dir already routes custom state directories, but callers must pass the resolved path explicitly.
- Six-process testing reproduced lost JSON history updates, and concurrent launch testing exposed a separate numeric-ID allocation race. The implementation now locks history and ledger mutations across processes and starts run creation with `BEGIN IMMEDIATE` before selecting the next reusable ID.
- The scripts_help registry currently has no runmux module entry. cli_tui is one-way reusable from runmux; runmux will depend on cli_tui, never the reverse.

## Architecture Decision

Use a separate RunmuxTuiApp controller composed with a RunmuxTuiAdapter and byte-log follower. The adapter keeps stable full IDs and invokes existing runmux APIs. The process browser is always available independently of the user-opened view tabs. Closing a view stops only its reader; closing the TUI stops only view readers and persists selected view IDs. Runmux-managed processes remain owned by their supervisors.

Reuse cli_tui viewport and ANSI helpers without subclassing CliTuiApp or changing direct-runner cleanup behavior. Render a bounded line-oriented transcript; do not claim to emulate arbitrary fullscreen terminal applications. Interactive programs use runmux's existing interact_run through a curses-to-raw-terminal handoff.

## Affected Files

Create:
- src/runmux/tui.py: browser, view tabs, launcher and lifecycle dialogs, curses lifecycle/handoff.
- src/runmux/tui_adapter.py: run record discovery, transient display status, managed launch/lifecycle, safe read-only view operations.
- src/runmux/log_follow.py: incremental UTF-8 decoding from byte logs, truncation detection, bounded transcript, background follow worker.
- src/runmux/workspace_state.py: atomic JSON under the selected Runmux state directory, keyed by canonical launch root and app identity, for explicitly opened full run IDs, selected view, and viewport state.
- tests/test_tui.py, tests/test_tui_adapter.py, tests/test_log_follow.py, tests/test_history_concurrency.py.

Modify:
- src/runmux/cli.py: add the tui subcommand without changing existing commands.
- src/runmux/history.py: add cross-process-safe atomic read-modify-write updates for history and saved-command JSON.
- pyproject.toml: add cli_tui as a one-way dependency and bump runmux MINOR.
- README.md: document TUI controls, ownership, log-view limits, and custom state isolation.
- modules/scripts_help/scripts_help/registry/registry.py: register runmux with the updated version.

Runmux's TUI continues to compose `cli_tui` view primitives without subclassing `CliTuiApp`. A separate user-authorized follow-up now adds generic root/app-scoped layout persistence and output capture to `cli_tui`; Runmux retains its custom-state workspace store and does not depend on the generic store.

## Risks and Review Focus

1. Reused numeric IDs must never retarget an open tab; test tab identity across record reordering and numeric-ID reuse.
2. UTF-8 multibyte sequences and ANSI escapes may cross file chunk boundaries; test incremental decoding, log truncation, missing files, and bounded memory.
3. TUI shutdown, tab close, deletion, and worker exceptions must never invoke runmux kill/terminate APIs; test each cleanup route.
4. Launch form parsing must preserve each argv token and cwd, including paths and argument values containing spaces; test the exact argv passed to create_managed_run.
5. Concurrent supervisor history writes must not lose sibling entries and must keep custom state directories isolated; test concurrent processes against temporary files.
