# Cycle 01: Startup Readiness

Status: implemented

## Implementation

- Poll the registry after supervisor creation until a port is published and the
  supervisor answers `status`.
- Apply readiness waiting to run, saved-command run, restart, and duplicate
  paths before automatic attachment.
- Detect terminal child status during startup and report status, exit code, and
  a short output-log tail.
- On timeout, leave the managed run intact and report an actionable attach
  command.
- Ensure failed/interrupted attachment restores terminal state.

## Tests

- Delayed port publication followed by successful status.
- Immediate child failure.
- Supervisor readiness timeout.
- Automatic attach waits for readiness.
- Existing suite remains green.

## Version

`0.7.1` to `0.7.2`.

## Verification

- 64 tests passed.
- Ruff passed.
- Black check passed.
- Compileall passed.
- Coverage completed.
- Real detached launch published a responsive supervisor before returning.

Last edited: 2026-06-22 06:09:10 -07:00
