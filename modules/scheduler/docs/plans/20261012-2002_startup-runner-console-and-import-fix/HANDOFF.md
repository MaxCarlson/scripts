# Handoff

## Current Stage

Stage 1: runner visibility and import collision.

## Branch and Approval

- Branch: `codex/kavita-module-mangadl-collections-20261009-0349`
- Commit: none
- Commit/push approval: not granted
- Merge approval: not granted

## State

The implementation and automated checks are complete in the current checkout. Preserve unrelated MangaDL, validation-report, and scheduler runtime-data changes. In particular, do not remove or move `modules/scheduler/run_requests/`.

## Next Action

The user should review the patch, run `scheduler setup windows` to update both registered actions, and confirm `scheduler tui` opens the log browser. The previous custom PowerShell theme also needs its missing `pscripts/atomic-custom.omp.json` source restored.
