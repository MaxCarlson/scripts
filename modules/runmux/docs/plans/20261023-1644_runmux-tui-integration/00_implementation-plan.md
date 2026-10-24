# Runmux Persistent Process Workspace Implementation Plan

> For implementers: use the executing-plans workflow and test-first steps. Checkboxes track implementation. No commit, push, merge, registry mutation, or live process action is authorized by this plan.

Goal: Add runmux tui as a persistent process browser, launcher, and multi-view workspace without coupling managed process lifetime to TUI lifetime.

Architecture: Runmux remains the process owner and supplies its existing registry, supervisor, IPC, logs, and lifecycle functions. A runmux-specific controller composes cli_tui view primitives and an adapter; byte-log following and UI workspace state stay in runmux. Closing views or the app only stops reader threads.

Tech Stack: Python 3.10+, curses, SQLite RunStore, supervisor IPC, byte logs, cli_tui >= 0.1.0, pytest.

Spec: docs/plans/20261023-runmux-tui-integration/ARCHITECTURE_ASSESSMENT.md and the user's Runmux/CLI TUI integration requirements.

## Global Constraints

- Preserve existing runmux CLI operations and current cli_tui consumer behavior.
- Keep dependencies one-way: runmux may depend on cli_tui; cli_tui must not depend on runmux.
- Use stable full run IDs internally; numeric IDs are display-only and reusable.
- Browser discovery is read-only and must not implicitly prune terminal registry records.
- TUI exit, view close, exceptions, and cleanup must never terminate runmux-managed processes.
- Use a bounded line transcript for logs; do not claim full arbitrary VT/xterm emulation.
- Use temporary isolated runmux state directories in tests; do not touch production runmux state.
- Preserve Windows 11, WSL2/Linux, macOS, and Termux behavior where practical.
- Do not commit, push, or merge.

## Review Focus

1. Full run ID remains attached to a view after record reordering or numeric-ID reuse.
2. UTF-8 and ANSI byte sequences split across reads render without replacement artifacts or unbounded buffers.
3. Missing or truncated log files recover without blocking the UI or discarding unrelated tabs.
4. Closing app, closing tabs, and reader exceptions do not call kill, terminate, or remove-run APIs.
5. Launch argv and cwd remain exact when tokens include spaces, quotes, REMAINDER arguments, or paths with spaces.

---

### Task 1: Read-only run adapter and bounded log following

Files:
- Create src/runmux/tui_adapter.py
- Create src/runmux/log_follow.py
- Create tests/test_tui_adapter.py
- Create tests/test_log_follow.py

Interfaces:
- RunmuxTuiAdapter(store: RunStore, history_path: Path) exposes list_runs() -> list[RunRecord], get_run(run_id: str) -> RunRecord, refresh_display_status(record: RunRecord) -> RunRecord. It uses store.list_runs(include_all=True), never listed_records or prune_terminal_runs. Display status refresh does not persist registry mutations.
- IncrementalLogReader(path: Path, *, max_lines: int = 10000, max_bytes: int = 4194304, chunk_size: int = 8192) exposes read_available() -> list[str], lines -> list[str], offset -> int, and error -> str | None.
- LogFollowWorker(reader: IncrementalLogReader, *, interval: float = 0.1) exposes start(), snapshot() -> list[str], stop() -> None.

Steps:
- [x] Write failing tests: discover active/paused/terminal records without pruning; preserve full IDs under numeric-ID reuse and reordered rows; format status overlays for responsive/dead supervisors without registry writes.
- [x] Run those tests and confirm expected missing API failures.
- [x] Implement adapter with direct store reads and transient dataclass replacements for display status.
- [x] Verify adapter tests pass; compare registry contents before and after.
- [x] Write failing log tests for split UTF-8, split ANSI, new bytes, huge output bounds, truncation, and missing/recreated files.
- [x] Implement incremental decoder and bounded transcript, with file reads only on worker threads in the app.
- [x] Run log tests and confirm retained bytes/lines stay within limits.

### Task 2: Workspace state and browser/view TUI

Files:
- Create src/runmux/workspace_state.py
- Create src/runmux/tui.py
- Create tests/test_tui.py
- Modify src/runmux/cli.py
- Modify pyproject.toml
- Modify README.md
- Modify modules/scripts_help/scripts_help/registry/registry.py

Interfaces:
- WorkspaceStateStore(state_dir: Path, root_dir: Path, app_id: str = "runmux") reads/writes schema-versioned atomic JSON under state_dir/workspaces, keyed by canonical launch root and app identity. It stores explicitly opened full run IDs, active full run ID, and per-view scroll offsets; it never enumerates all history as tabs.
- RunmuxTuiApp(adapter: RunmuxTuiAdapter, state_store: WorkspaceStateStore, *, handoff: Callable[[str], None] | None = None) owns UI and log readers only. close_view(run_id), close(), and quit() must not call runmux process lifecycle operations.
- Add CLI handle_tui(args) and parser subcommand tui, using the existing global --state-dir and separator options.
- Add cli_tui >= 0.1.0 to runmux dependencies; bump runmux minor version and synchronize the help registry entry.

Steps:
- [x] Write failing tests for browser rows, search/filter selection, opening multiple user-selected views, independent scroll offsets, workspace restart restore, unknown saved run IDs, and no auto-open of historical runs.
- [x] Write failing tests proving close view, delete-all views, q quit, force quit, and injected view-reader exceptions do not call managed lifecycle functions.
- [x] Implement versioned workspace persistence keyed by canonical launch root and app identity within RunStore.state_dir; restore only saved full IDs that still exist.
- [x] Implement RunmuxTuiApp using curses and cli_tui OutputViewport/ANSI/footer primitives. Keep the browser independent from tabs.
- [x] Add and test runmux tui dispatch; runmux tui must use the supplied state directory for registry, history, workspace state, and saved commands.
- [x] Add hotkeys/help text and registry metadata; preserve existing runmux command forms.
- [x] Run targeted TUI tests and both package suites; compare current baseline runmux failures by name.

### Task 3: Launch, history, lifecycle, and concurrency

Files:
- Modify src/runmux/tui.py
- Modify src/runmux/tui_adapter.py
- Modify src/runmux/history.py
- Create tests/test_history_concurrency.py
- Extend tests/test_tui.py and tests/test_tui_adapter.py

Interfaces:
- RunmuxTuiAdapter.launch(argv: list[str], *, cwd: Path, name: str | None = None) -> RunRecord delegates to create_managed_run and returns the created record.
- RunmuxTuiAdapter.kill(run_id: str, *, force: bool) -> RunRecord, pause(run_id: str), resume(run_id: str), restart(run_id: str) -> RunRecord, duplicate(run_id: str) -> RunRecord, and remove_terminal(run_id: str) delegate to existing runmux functions using the full ID.
- Launcher arguments use a JSON array of strings so quoting and spaces are unambiguous; UI preview shows exact argv and cwd before launch.
- History and saved-command reads/writes always pass history_path_for_state_dir(store.state_dir).

Steps:
- [x] Write failing UI tests for exact program/argv/cwd preview and launch, history/saved-command lookup in custom state, and explicit confirmation before kill or terminal-record removal.
- [x] Write failing concurrency tests with multiple processes recording distinct run starts/finishes and saved commands to one temporary history path.
- [x] Implement an OS-backed cross-process lock around complete history read-modify-write operations and atomic replacement; cover history JSON and unique-command ledger.
- [x] Wire manual launcher, command history, saved commands, and lifecycle controls to runmux Python APIs, never subprocess-wrapped runmux CLI calls.
- [x] Test pause/resume, kill confirmation, restart constraints, duplicate, remove confirmation, lost supervisor, and IPC failure handling.
- [x] Verify saved history remains isolated to a custom state directory and parallel updates are not lost.

### Task 4: Interactive attachment handoff and platform polish

Files:
- Modify src/runmux/tui.py
- Extend tests/test_tui.py
- Modify README.md and plan handoff

Interfaces:
- RunmuxTuiApp.request_attach(run_id: str) records a handoff request and returns from curses; the outer run loop calls existing client.interact_run(store, record), then reconstructs the app and reopens curses.
- View state persists full run IDs and independent viewport offsets across the handoff.

Steps:
- [x] Write failing tests for curses exit before interact_run, detach returning to the same selected view, run exit during attach, and IPC/input-lock failure restoring the TUI.
- [x] Implement controlled handoff through the existing interact_run API; do not embed terminal emulation.
- [x] Add visible status/error messages and keep registry, IPC, and log reads off the UI event loop.
- [x] Run full runmux and cli_tui suites, focused Ruff, and compile checks. Compare baseline failures and report new failures separately.
- [x] Record Windows pseudo-terminal smoke and Windows Terminal/WSL2 validation gaps.

### Optional follow-up: Registered-module generated forms

- Explore only after manual argv launch is stable.
- Reuse scripts_help registry entries when they identify an importable argparse builder.
- Do not execute registry help commands as subprocesses to launch runs.
- Add the integration only for modules with a safe parser factory and tests for exact argv generation.
- Keep it out of the initial acceptance gate.
