# Windows Listener and CLI Presentation Corrections

## Status

- Starting checkpoint: `6edbc8fbeae5407698bd6861e8114be9a82bc282`
- Work branch: `codex/resource-coordinator-windows-listener-readable-cli-20261106`
- Worktree: `.worktrees/resource-coordinator-upgrade-20261106`
- Live deployment actions: none authorized or performed.

## Stages

1. [x] Add listener discovery and presentation regression tests; record red results.
2. [x] Implement Windows native listener identity and fail-closed upgrade diagnostics.
3. [x] Implement schema-aware human renderers while preserving JSON.
4. [x] Run focused and regression validation, update docs, review scoped diff.
5. [x] Commit as `a7fe8b93`, fast-forward local `main`, verify remote `main` was still at
   the reviewed parent, and push the integrated implementation.

## Latest validation

- Focused RC suites: 305 passed, 1 skipped, including installation, listener discovery, CLI,
  service lifecycle, credentials, miner/gaming, and gateway regressions.
- Protected bridge routing: 31 passed.
- Ruff: passed for all changed Python files.
- `compileall`: passed for the Resource Coordinator package.
- `git diff --check`: passed.
- Broad package suite (run before the final listener-exit regression additions): 604 passed,
  5 skipped, 6 failed. Failures were two stale tests
  calling removed private miner methods, a simulated acceptance cooldown timing assertion,
  a stale recovery-token test setup, the live loopback test's occupied production port,
  and the supervised live test's safe refusal due to the already-running KRig process.
- The disposable-loopback listener integration test is skipped because this runner cannot
  see its own bound socket in the Windows TCP table. The native table structure, byte order,
  buffer-growth retry, and current-process identity are independently tested.
- A fresh combined rerun in the current shell stalled after the first CLI test batch began;
  it was interrupted locally. The standalone listener suite completed again with 14 passed,
  1 skipped. Do not treat the interrupted rerun as a pass; the completed 305-test focused
  run above remains the latest full regression evidence.
