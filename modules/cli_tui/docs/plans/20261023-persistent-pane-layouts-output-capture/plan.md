# Persistent Pane Layouts and Output Capture

## Objective

Implement the approved design in docs/specs/2026-10-23-persistent-pane-layouts-and-output-capture-design.md for cli_tui: save and restore layouts by app and launch directory, offer save-on-exit for normal quit, preserve immediate uppercase Q, and save retained/future pane output to a chosen file.

## Plan

1. **Inventory and persistence model**
   - Inspect package code and test conventions.
   - Add serializable layout models and config-path/identity helpers.
   - Use schema-versioned JSON, validation, and atomic writes.
   - Add focused persistence tests for identity isolation, round trip, invalid files, and no command auto-run.

2. **Restore and save interactions**
   - Reconstruct supported command and console panes on app startup.
   - Preserve order and active pane; skip invalid panes safely with a notice.
   - Add pane-manager save hotkey and two-step normal quit/save prompt.
   - Verify uppercase Q still bypasses prompts.
   - Add focused app/key-flow tests.

3. **Output file capture**
   - Add a thread-safe output subscription path to process/console runners.
   - Add Ctrl+O dialog for directory and filename, overwrite confirmation, retained transcript snapshot, and future output streaming.
   - Close capture handles on pane deletion and app shutdown; surface errors without affecting child processes.
   - Add focused capture, dialog, cancellation, and failure tests.

4. **Integration and validation**
   - Update package version for the backward-compatible feature.
   - Run focused cli_tui tests and relevant lint/type checks supported by the module.
   - Record exact validation and any remaining manual Windows terminal acceptance in this plan and module handoff.

## Constraints

- Do not persist live subprocess state or rerun commands during restore.
- Keep config outside project roots and key layouts by normalized launch directory plus stable app ID.
- Preserve unrelated workspace changes. Do not commit, push, or merge.
- Keep tests isolated to the module's established temp root.
