# Part 2 Checklist

- [x] Synchronize Part 1 status-only commits with `main`.
- [x] Create isolated worktree from the synchronized mainline.
- [x] Verify finalized V3 SHA-256 and blob in the worktree.
- [x] Inspect module-specific instructions and existing CLI/gateway/status architecture.
- [x] Add regression tests before implementation for each behavior change.
- [x] Implement the canonical CLI/package transition and compatibility behavior.
- [x] Implement status sanitization, gaming/maintenance visibility, and telemetry provenance.
- [x] Implement authenticated maintenance reconciliation with read-only defaults.
- [x] Implement read-only inference aggregation, bounded LM Studio observer, and recovery assessment.
- [x] Implement human renderers and stable JSON output.
- [x] Run focused and regression suites; classify all failures, skips, and known baseline defects.
- [x] Run Ruff, compilation, scoped `git diff --check`, and isolated entry-point validation.
- [x] Update Part 2 status and module documentation; review safety and compatibility diff.
- [x] Commit and push feature branch; verify remote SHA and clean worktree.
