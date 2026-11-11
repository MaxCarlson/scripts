# Durable GPU Maintenance Sessions — Checklist

## Ownership and setup

- [x] Verify integrated baseline and preserve dirty primary checkout.
- [x] Create isolated feature worktree and branch.
- [x] Record baseline Python/platform and worktree ownership state.

## Implementation

- [x] Extend durable state compatibly for maintenance lifecycle and recovery.
- [x] Add shared GPU admission fence covering reservations and idle-guarded transitions.
- [x] Implement maintenance manager, operation identity, token lifecycle, heartbeat, expiry, release, and restart recovery.
- [x] Integrate safe miner stop, ownership verification, restart inhibition, and startup gating.
- [x] Gate inference/model load before model reuse; gate manual/gaming/automatic miner paths.
- [x] Add authenticated canonical maintenance routes and sanitized status.
- [x] Add safe lifecycle events.
- [x] Document API, restoration evidence, expiry, and logical-fencing limits.

## Validation

- [x] State migration, corruption, and unrelated-field preservation tests.
- [x] Admission conflict/race and cancellation tests.
- [x] Fake-miner acquisition, renewal, release, expiry, and restart tests.
- [x] Gateway authentication, idempotency, errors, status sanitization, and retry tests.
- [x] Mining client compatibility report; Mining repository unchanged.
- [x] Focused RC suites (214 passed, one baseline failure deselected), Ruff, compilation, and `git diff --check`.
- [x] Review final diff and confirm no production operations.

## Delivery

- [x] Update status and record exact commands/results.
- [x] Commit scoped work on feature branch (`1d6adb31e4382d55bca77fb7469fa0349f7e95ee`).
- [x] Push feature branch to origin; do not merge or deploy.
