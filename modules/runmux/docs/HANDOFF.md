# Runmux Current Handoff

Last updated: 2026-07-19 07:46:07 -07:00

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
8. `plans/20260622-0551_runmux-multi-attach-input-lock-history/04_history-search-and-summary__planned.md`

## Current State

- Cycle 1 was committed as `f697615`.
- Stage 2 was committed as `1cb73e4` and manually approved on 2026-07-19.
- Current branch is `main`; verify it again before implementation or commit work.
- Runmux source version is `0.9.0`.
- Stage 2 automated verification passed and the user confirmed concurrent
  terminals can interact with or view the same managed run.
- Stage 4 history display, filtering, common-command, replay, interactive, and
  fzf code is implemented but awaiting user-run tests and manual validation.
- Documentation now includes a detailed project README, reusable AGENTS policy,
  and HANDOFF files in every created documentation directory.
- The active implementation plan is self-contained under
  `docs/plans/20260622-0551_runmux-multi-attach-input-lock-history/`.
- Its checklist begins with plan creation, stage completion, and full-plan
  completion timestamps.
- Current branch: `main`.

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

## Manual Validation

The user confirmed on 2026-07-19 that multiple terminals can interact with or
view the same managed run. The original validation procedure was:

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

## Known Risks

- Stage 3 persistent configuration remains incomplete even though attachment
  status rendering exists in the current code.
- Stage 4 storage migration/retention remains unfinished.
- Existing overall coverage remains modest because older CLI/supervisor paths
  have limited tests, though new state/store logic has direct coverage.

## Next Action

Run the user-owned targeted test commands and manually validate the Stage 4
history workflow. The second-round requirements are coded but not validated:
isolated test-history routing, legacy probe filtering, left-aligned/multiline
colored metadata, combined/clearable filters, metadata/full-content toggles,
and the multi-instance original/current/custom-path run dialog. Normal history
now records only `runmux run` launch paths; restart and duplicate clones are
excluded. Do not commit before validation.
