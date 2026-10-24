# Checklist

## Inventory and persistence
- [x] Confirm package interfaces, current tests, and app identity source.
- [x] Add layout identity/path and versioned JSON persistence.
- [x] Test round-trip, identity scoping, corrupt/incompatible data, and atomic write behavior.
- [x] Reconstruct saved panes without starting prior commands.

## Save/quit interactions
- [x] Add pane-manager save shortcut and status feedback.
- [x] Add save-layout question after normal quit confirmation.
- [x] Preserve uppercase Q immediate quit semantics.
- [x] Test each key flow and save failure behavior.

## Output capture
- [x] Add output listeners with safe thread handoff.
- [x] Add output destination dialog and overwrite confirmation.
- [x] Save retained transcript and append future output.
- [x] Close capture cleanly on pane deletion and shutdown.
- [x] Test snapshot/streaming, validation, cancellation, and I/O errors.

## Release and validation
- [x] Bump cli_tui minor version.
- [x] Run focused tests and applicable static checks.
- [x] Update handoff/status with results and remaining Windows manual checks.
- [ ] Complete interactive Windows terminal acceptance.
