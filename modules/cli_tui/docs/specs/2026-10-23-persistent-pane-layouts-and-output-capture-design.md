# Persistent Pane Layouts and Pane Output Capture

## Intent

Add restartable pane layouts and user-selected output capture to the reusable `cli_tui` package. The same app, launched again from the same working directory, should restore its saved pane arrangement without automatically rerunning prior commands. Users should also be able to save a pane's retained output and capture subsequent output to a chosen file.

## Goals

- Save and restore the ordered pane layout, active pane, command navigation/form values, and console working directories.
- Identify a layout by both the normalized launch directory and the TUI application, so different apps in one directory do not overwrite or load each other's panes.
- Ask whether to save the layout when the user exits through normal `q` confirmation.
- Keep uppercase `Q` as an immediate force quit that skips layout-saving prompts.
- Add a hotkey that opens a small dialog for an output directory and filename.
- On output save, write the pane's currently retained transcript and capture later output while that pane remains open.
- Keep storage versioned and recover safely from malformed or incompatible layout files.

## Non-Goals

- Do not persist or restart live subprocesses, process IDs, shell history execution state, or current telemetry.
- Do not automatically log pane output unless the user invokes the save-output action.
- Do not share layouts across different apps or different launch directories.
- Do not silently overwrite an existing output file.

## Current State and Constraints

- `PaneWorkspace` keeps `PaneSession` objects in memory; each pane contains navigation, optional `FormState`, runner, viewport, title, and pane type.
- `FormState` contains parser-specific `CliCommand` objects and values, so persistence must serialize plain data rather than pickle Python objects.
- `ProcessRunner` merges stderr into stdout and keeps a bounded 10,000-line virtual-terminal buffer. It currently has no output-listener or file-capture interface.
- `ConsolePaneRunner` maintains a pane transcript and creates `ProcessRunner` instances for shell commands.
- Lowercase `q` currently asks whether to exit; uppercase `Q` immediately terminates all panes. Keep `Q`'s emergency behavior.
- The pane manager already has modal key routing and is the place for an explicit save-layout action. Running panes already have global hotkeys and footers.

## Chosen Design

### Layout identity and storage

- Add an optional stable `layout_id` to `CliTuiApp`; derive a default from the root command's program name and executable when callers omit it.
- Key a layout by the normalized absolute launch directory plus `layout_id`. Store files under the user's config directory: `%LOCALAPPDATA%\\cli_tui\\layouts` on Windows, `$XDG_CONFIG_HOME/cli_tui/layouts` when configured, or `~/.config/cli_tui/layouts` otherwise.
- Use JSON with a schema version and the canonical directory/app identity in the payload. Hash the identity for the filename; validate the payload identity on load.
- Save atomically through a temporary sibling file and replace. Ignore corrupt, unsupported, or mismatched layouts, keep the default single-pane workspace, and show a non-fatal notice.

### Serialized pane state

Persist only plain data needed to reconstruct each pane:

- pane title and type;
- command navigation path, current menu/form state, and JSON-compatible form values;
- console working directory;
- pane order and active index.

On load, reconstruct command panes from the current app's parser. A pane that references a removed command or invalid form state is skipped with a notice. A pane that was running when saved restores to its form/configuration state, or its command menu if no form exists. No command starts automatically. Console panes restore as idle consoles at their saved working directories.

### Save and quit interactions

- Add `s` / `S` to the pane-manager overlay to save the current layout immediately; show a short success or failure message.
- Keep the existing `q` exit confirmation. After the user confirms exit, ask whether to save the pane layout. Choosing no exits without saving; choosing yes saves and exits.
- A layout-save failure must not silently discard the user's choice. Show the error and let the user retry, return to the app, or quit without saving.
- Keep uppercase `Q` as immediate quit with no save prompt.

### Pane output capture

- Add `Ctrl+O` as the output-save hotkey. It opens a modal with separate directory and filename fields, defaulting to the launch directory and a sanitized pane-title-based `.log` filename.
- Confirm before overwriting an existing file. Keep the dialog open on invalid paths or write errors.
- Write the pane's retained transcript as UTF-8 when capture starts, then attach a thread-safe output listener and append later decoded output while that pane remains open. Do not exceed the existing in-memory history cap; file capture itself is streamed.
- For an already-finished pane, save its currently retained transcript as a snapshot. For console panes, include current console history and continue capturing subsequent command output while the pane remains open.
- Close capture writers when the pane is deleted or the TUI shuts down. A failed capture should detach cleanly and report the destination and error without disrupting the child process.

## Approaches Considered

1. **Store layouts in each launch directory.** Rejected because it adds files to arbitrary project roots and can dirty repositories.
2. **Use one global layout for every TUI app.** Rejected because command panes depend on each app's parser and could restore to unrelated commands.
3. **Use user config storage keyed by launch directory and app, with versioned JSON.** Chosen because it avoids workspace pollution and keeps parser-specific layouts isolated while allowing reliable automatic restore.

For output, a one-time snapshot would be simpler but would miss output produced after the hotkey is pressed. The chosen behavior writes the retained transcript and streams future output to the same file until that pane closes.

## Acceptance Checks

- A saved layout is restored only for the same normalized launch directory and app identity.
- Different apps in one directory and the same app in different directories load independent layouts.
- Saving/restoring retains pane order, active pane, command form values, and console working directories.
- Restoring a previously running pane never starts the command automatically.
- Corrupt, incompatible, or partially invalid layouts fall back safely without crashing the TUI.
- Normal `q` offers layout saving; uppercase `Q` exits immediately without prompts.
- The output dialog validates directory/filename, prevents accidental overwrite, saves retained output, and captures future output without blocking the UI or child process.
- Pane deletion and TUI shutdown close output writers; filesystem errors are visible and do not break process execution.
- Focused headless tests cover persistence, key flow, output capture, cancellation, and error cases; real Windows terminal interaction is reviewed manually.
