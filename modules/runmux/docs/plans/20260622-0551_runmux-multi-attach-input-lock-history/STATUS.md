# Multi-Attach and History Status

Last updated: 2026-06-22 06:44:27 -07:00

## Current Position

- [x] Master and cycle plans recorded.
- [x] Cycle 1 committed as `f697615`.
- [x] Cycle 2 implementation complete.
- [x] Cycle 2 existing and new tests pass.
- [ ] Cycle 2 committed.
- [ ] Cycle 3 complete.
- [ ] Cycle 4 complete.

Current cycle: **02 - Multi-Attach and Input Lock**

Plan branch: `runmux-multi-attach-input-lock-history-20260622-0551`

Branch state: active on the required branch. Work began on `main` before the
branch rule existed and was moved before the Cycle 2 commit.

Manual approval policy:

- [x] Cycle 1 was committed before this policy was requested.
- [x] Cycle 2 staged for user testing.
- [ ] User approved Cycle 2.
- [ ] Cycle 2 committed after approval.

## Cycle 1: Startup Readiness

- [x] Wait for supervisor port and responsive status before returning.
- [x] Apply readiness to all paths using `create_managed_run`.
- [x] Report startup status, exit code, and output tail.
- [x] Leave timed-out runs registered with an attach hint.
- [x] Stop and join interact output threads when input attachment fails.
- [x] 64 tests passed.
- [x] Ruff, Black check, compileall, coverage, and detached smoke passed.

## Cycle 2: Multi-Attach and Input Lock

- [x] Add persistent attachment-session schema.
- [x] Add lifetime view/interact counters.
- [x] Add supervisor-local FIFO lock coordinator.
- [x] Add minimum-tenure and idle-transfer primitives.
- [x] Wire view clients to registration and heartbeat IPC.
- [x] Wire interact clients to concurrent input IPC and heartbeat.
- [x] Add lowercase `l` lock request command.
- [x] Add current/lifetime counts to list and JSON.
- [x] Expire stale sessions and hand off lock ownership.
- [x] Replace obsolete exclusive-session tests.
- [x] Add store, supervisor, IPC, client, and list tests.
- [x] Add project introduction, LLM workflow, and folder-specific handoff documents.
- [x] Move the implementation plan into its dated self-contained `docs/plans/` folder.
- [x] Run complete automated verification.
- [ ] Receive user manual approval and commit Cycle 2.

## Cycle 3: Attachment UI and Configuration

- [ ] Persistent responsive top status row.
- [ ] Persistent bottom warning/input-owner row.
- [ ] ANSI-safe managed viewport.
- [ ] Direct view hotkeys and persistent runmux input mode.
- [ ] Per-session top/bottom toggles.
- [ ] Validated `config` and `settings` commands.

## Cycle 4: History Search and Summary

- [ ] Locked JSONL history and separate saved-command storage.
- [ ] Existing history migration and backup.
- [ ] Retention configuration.
- [ ] Incremental prefix/contains search.
- [ ] Recent/frequency ordering.
- [ ] Filtered summaries and JSON output.

## Latest Verification

Cycle 1:

```text
pytest --tb=short -q .\modules\runmux\  -> 64 passed
ruff check ...                         -> passed
black --check --line-length 120 ...    -> passed
python -m compileall ...               -> passed
```

Cycle 2:

```text
pytest --tb=short -q .\modules\runmux\  -> 72 passed
ruff check ...                         -> passed
black --check --line-length 120 ...    -> passed
python -m compileall ...               -> passed
coverage                               -> 54% overall, store 89%
real IPC smoke                         -> I:2 V:1 T:3 L:1 Q:1
```

## Next Action

Wait for user manual testing of concurrent interact sessions and lock handoff.
Do not commit or begin Cycle 3 until explicit approval.
