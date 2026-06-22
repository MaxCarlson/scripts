# Runmux Implementation Checklist

Plan created: 2026-06-22 05:51:54 -07:00

Last updated: 2026-06-22 06:44:27 -07:00

Full plan completed: pending

Plan branch: `runmux-multi-attach-input-lock-history-20260622-0551`

Plan branch merged: pending

## Plan Progress

- [x] Stage 1: Startup Readiness - completed 2026-06-22 05:54:24 -07:00
- [ ] Stage 2: Multi-Attach and Input Lock - in progress; automated verification complete, manual approval pending
- [ ] Stage 3: Attachment UI and Configuration - planned
- [ ] Stage 4: History Search and Summary - planned

This is the feature-level implementation and verification ledger for this
implementation plan. See applicable global/repository LLM instructions for
generic rules, `../../README.md` for project context, and this folder's
`HANDOFF.md` and `STATUS.md` for current plan state.

## Stage 1: Startup Readiness

### Implemented and tested

- [x] Supervisor readiness polling - implemented and tested.
- [x] Responsive port/status verification - implemented and tested.
- [x] Startup timeout with actionable attach hint - implemented and tested.
- [x] Immediate failure status, exit code, and log tail - implemented and tested.
- [x] Interact cleanup after input-channel failure - implemented and tested.
- [x] Run, saved-command, restart, and duplicate paths share readiness - implemented and tested.

Automated result: 64 tests passed before user approval policy was introduced.

## Stage 2: Multi-Attach and Input Lock

### Implemented and tested

- [x] Attachment-session SQLite schema - implemented and tested.
- [x] Lifetime view/interact counters - implemented and tested.
- [x] Current attachment lease summaries - implemented and tested.
- [x] Concurrent supervisor session registry - implemented and tested.
- [x] FIFO input-lock coordinator - implemented and tested.
- [x] First interactor receives initial ownership - implemented and tested.
- [x] Minimum-tenure and idle-transfer behavior - implemented and tested.
- [x] Holder disconnect handoff - implemented and tested.
- [x] Stale-session expiry - implemented and tested.
- [x] Interact registration and heartbeat - implemented and tested.
- [x] View registration and heartbeat - implemented and tested.
- [x] Lowercase `l` input-lock request - implemented and tested.
- [x] Reject program input from non-holders - implemented and tested.
- [x] `runmux ls/list` attachment columns - implemented and tested.
- [x] List JSON attachment and lock fields - implemented and tested.
- [x] Reusable global LLM planning and handoff policy export - implemented and reviewed.
- [x] Detailed project and architecture introduction in `docs/README.md` - implemented and reviewed.
- [x] Current runmux-specific resume state in `docs/HANDOFF.md` - implemented and reviewed.
- [x] Handoff files in every created documentation subfolder - implemented and reviewed.
- [x] Dated self-contained `docs/plans/` folder structure - implemented and reviewed.
- [x] Plan progress ledger with stage completion timestamps - implemented and reviewed.
- [x] Generic-to-project-to-plan document navigation - implemented and reviewed.
- [x] Master and stage plan last-edited timestamps - implemented and reviewed.
- [x] Existing and new Stage 2 tests pass together.
- [x] Ruff, Black check, compileall, and coverage pass.
- [x] Stage 2 staged for manual user testing.
- [ ] User manually approves Stage 2.
- [ ] Stage 2 committed.

Automated result: 72 tests passed. Real supervisor IPC smoke confirmed
`I:2 V:1 T:3 L:1 Q:1` and matching JSON fields.

## Stage 3: Attachment UI and Configuration

- [ ] Thread-safe attachment renderer.
- [ ] Reserved top status row.
- [ ] Reserved bottom warning/input-owner row.
- [ ] ANSI-safe managed viewport.
- [ ] Responsive connection/runtime formatting.
- [ ] Timed connection warnings.
- [ ] Input ownership and queue indicators.
- [ ] Direct runmux hotkeys in view mode.
- [ ] Persistent runmux-input mode.
- [ ] Per-session top/bottom row toggles.
- [ ] Validated config storage.
- [ ] `runmux config` and `runmux settings`.

## Stage 4: History Search and Summary

- [ ] Locked JSONL history.
- [ ] Separate saved-command storage.
- [ ] Existing history migration and backup.
- [ ] Configurable retention.
- [ ] Exit-code and attachment history fields.
- [ ] Prefix and contains filtering.
- [ ] Recent and frequency ordering.
- [ ] Incremental interactive search.
- [ ] Filtered text and JSON summaries.
