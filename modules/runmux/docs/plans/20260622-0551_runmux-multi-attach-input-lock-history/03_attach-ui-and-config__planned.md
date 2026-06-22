# Cycle 03: Attachment UI and Configuration

Status: planned

## Implementation

- Add a thread-safe attachment renderer.
- Reserve configurable top and bottom rows without modifying raw ANSI logs.
- Maintain the child viewport across screen-clear, home, alternate-screen,
  origin-mode, and scroll-region control sequences.
- Render responsive connection/runtime and input-lock status.
- Show timed connection warnings.
- Add direct view hotkeys, persistent runmux-input mode, and row toggles.
- Add validated `runmux config` and `runmux settings` aliases.

## Tests

- Wide and narrow status formatting.
- Split ANSI control sequences.
- Resize and row toggles.
- Warning expiry and input-state indicators.
- Config defaults, mutation, reset, and validation failures.

Last edited: 2026-06-22 06:09:10 -07:00
