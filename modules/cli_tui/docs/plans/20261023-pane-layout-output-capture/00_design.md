# Persistent CLI TUI Panes and Output Capture

**Goal:** Let existing `CliTuiApp` consumers save pane layouts by launch root and app, restore them on the next launch, and export active pane output to a selected UTF-8 file.

**Design:** Keep persistence and output capture as small `cli_tui` modules. Persist UI state only; never relaunch a process from a saved layout. Add optional decoded-output subscriptions to `ProcessRunner` and keep the direct subprocess backend and cleanup semantics intact.

**Decisions:** Layout identity is canonical launch directory plus app ID. `Ctrl+S` saves immediately; confirming `q` asks whether to save. `Ctrl+O` opens a two-field directory/filename dialog and asks before overwriting. `Q` preserves its immediate force-quit behavior.

## Review Focus

- Running panes restore as static output without re-executing their command.
- Direct-runner deletion and quit behavior remains unchanged.
- UTF-8 stream output and existing-file protection are preserved.
- Save failures leave the quit prompt available for retry or exit without saving.
- Runmux-specific layout state remains isolated from generic CLI TUI state.
