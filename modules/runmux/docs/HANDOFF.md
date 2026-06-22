# Runmux Current Handoff

Last updated: 2026-06-22 06:44:27 -07:00

## Resume Here

Runmux is midway through the multi-attach, input-lock, attachment UI, and
history roadmap.

Read in this order:

1. Applicable global and repository-level LLM instructions
2. `README.md`
3. `plans/HANDOFF.md`
4. `plans/20260622-0551_runmux-multi-attach-input-lock-history/HANDOFF.md`
5. `plans/20260622-0551_runmux-multi-attach-input-lock-history/STATUS.md`
6. `plans/20260622-0551_runmux-multi-attach-input-lock-history/checklist.md`
7. `plans/20260622-0551_runmux-multi-attach-input-lock-history/00_implementation-plan.md`
8. `plans/20260622-0551_runmux-multi-attach-input-lock-history/02_multi-attach-input-lock__in_progress.md`

## Current State

- Cycle 1 was committed as `f697615`.
- Cycle 2 code and documentation are staged but intentionally uncommitted.
- Required plan branch is
  `runmux-multi-attach-input-lock-history-20260622-0551`.
- This work began on `main` before the branch rule was introduced. The staged
  work has now been moved to the required plan branch.
- Runmux source version is staged as `0.8.0`.
- Cycle 2 automated verification passed.
- The assistant must wait for user manual approval.
- Do not begin Cycle 3.
- Do not commit Cycle 2 without explicit approval.
- Documentation now includes a detailed project README, reusable AGENTS policy,
  and HANDOFF files in every created documentation directory.
- The active implementation plan is self-contained under
  `docs/plans/20260622-0551_runmux-multi-attach-input-lock-history/`.
- Its checklist begins with plan creation, stage completion, and full-plan
  completion timestamps.
- Current branch: `runmux-multi-attach-input-lock-history-20260622-0551`.

## Cycle 2 Implementation

- SQLite attachment-session schema and lifetime counters.
- View and interact registration with heartbeat leases.
- Concurrent interact clients.
- Supervisor-owned FIFO input lock.
- First interactor receives initial ownership.
- Lowercase `l` requests ownership from Ctrl-X command mode.
- Ten-second minimum tenure and 250 ms input-idle transfer.
- Immediate holder-disconnect handoff.
- Stale-session expiration.
- Input from non-holders is discarded rather than replayed.
- `runmux ls/list` and JSON expose attachment and lock counts.

## Verification Evidence

```text
pytest --tb=short -q .\modules\runmux\  -> 72 passed
ruff check ...                         -> passed
black --check --line-length 120 ...    -> passed
python -m compileall ...               -> passed
coverage                               -> 54% overall, store 89%
real IPC smoke                         -> I:2 V:1 T:3 L:1 Q:1
```

## Manual Test Gate

The user should test:

1. Start an indefinitely interactive managed program.
2. Open two `runmux interact` clients for the same run.
3. Verify Ctrl-X works independently in both clients.
4. Verify only the first client initially controls program input.
5. In the second client press Ctrl-X, then lowercase `l`.
6. Verify it reports queue position 1.
7. After minimum tenure and holder inactivity, verify control transfers.
8. Add a view client and check live output.
9. Check `runmux ls` current/lifetime and lock counts.
10. Detach clients and confirm current counts drop while lifetime totals remain.

Cycle 3 status bars and persistent visible lock indicators are not expected yet.

## Known Risks

- Full manual multi-terminal behavior has not yet been approved.
- Lock feedback is currently a Ctrl-X message and list column, not a persistent
  status bar.
- Stage 3 will add the reserved terminal rows and richer input-owner display.
- Existing overall coverage remains modest because older CLI/supervisor paths
  have limited tests, though new state/store logic has direct coverage.

## Next Action

Wait for the user's manual test result. If approved:

1. Mark manual approval in the active plan's `checklist.md` and `STATUS.md`.
2. Rename Cycle 2 to `__implemented.md`.
3. Update plan timestamps and links.
4. Commit the staged Cycle 2 change.
5. Confirm a clean worktree.
6. Plan Cycle 3 and populate its checklist before implementation.

If testing fails, fix Cycle 2, update documents, rerun all verification, restage,
and request another manual test.
