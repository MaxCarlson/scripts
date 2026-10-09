# Graceful lifecycle checklist

## Stage 1

- [x] Diagnose archive decisions for the live scratch run.
- [x] Confirm cleaned partial URLs were downloaded rather than skipped.
- [x] Inspect existing runtime worker scaling behavior.
- [x] Implement graceful `q` drain-and-quit.
- [x] Implement immediate `Ctrl+Q` and retain `Ctrl+C` behavior.
- [x] Clarify worker scaling and quit controls in the dashboard.
- [x] Use an eight-worker ceiling for scratch/SSD and four for rotational or
  unknown storage; expose `-m/--max-workers` in normal help.
- [x] Clean up retired rows and selection after workers drain.
- [x] Add focused tests for success and failure paths.
- [x] Bump and synchronize MangaDL's minor version.
- [x] Update README and handoff documentation.
- [x] Run repository dispatcher (MangaDL 224 passed; cross-platform 110 passed,
  4 skipped; compile and Ruff checks passed for both).
- [ ] Run final scoped diff checks and stop for user validation/commit approval.
