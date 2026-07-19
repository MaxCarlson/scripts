# Runmux Implementation Checklist

Plan created: 2026-06-22 05:51:54 -07:00

Last updated: 2026-07-19 07:58:00 -07:00

Full plan completed: pending

Plan branch: `runmux-multi-attach-input-lock-history-20260622-0551`

Plan branch merged: pending

## Plan Progress

- [x] Stage 1: Startup Readiness - completed 2026-06-22 05:54:24 -07:00
- [x] Stage 2: Multi-Attach and Input Lock - committed and manually approved 2026-07-19
- [ ] Stage 3: Attachment UI and Configuration - partially implemented; persistent configuration remains
- [ ] Stage 4: History Search, Replay, and Summary - detailed plan updated 2026-07-19

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
- [x] User manually approved Stage 2 on 2026-07-19: multiple terminals can interact with or view one run.
- [x] Stage 2 committed as `1cb73e4`.

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
- [x] Global newest-first history IDs coded: latest `0`, second latest `1`; tests added, not run.
- [x] Global IDs preserved in filtered, common, interactive, fzf, and JSON views; tests added, not run.
- [x] Exact argv replay coded with `runmux run -H/--history -i/--id ID`; tests added, not run.
- [x] Original cwd validation/replay coded with `-P/--path`; tests added, not run.
- [x] Case-insensitive `--starts-with` and `--contains` filtering coded; tests added, not run.
- [x] Most-common grouping coded with default 10 and argument override; tests added, not run.
- [x] Matching is applied before most-common grouping.
- [x] Default output changed to history ID and command only.
- [x] Optional date, path, status/exit-code, and runtime fields coded.
- [x] Interactive multi-row browser coded with persistent bottom hotkey help.
- [x] Interactive navigation, run (`r`), save (`s`), print (Enter), search, and quit actions coded.
- [x] Optional fzf mode coded with global-ID selection and print/run/save actions.
- [x] Filtered text and structured JSON output coded.
- [x] Focused ID, replay, filter, common, browser, metadata, and fzf tests added but not run.
- [x] Isolated-state history routing and legacy internal-probe filtering coded; tests added, not run.
- [x] Restart/duplicate clones are excluded from normal history; test added, not run.
- [x] Left-aligned IDs and multiline path/status/date/runtime formatting coded; tests updated, not run.
- [x] Status-aware metadata colors and distinct path color coded.
- [x] Normal text history prints oldest-to-newest while preserving global newest-first IDs; ID marker changed to red `(ID).`; tests updated, not run.
- [x] Date/time is rendered on its own status-colored line; tests updated, not run.
- [x] Interactive prefix/contains filters can coexist, be replaced, and be cleared; focused combined-filter tests added, not run.
- [x] Interactive metadata visibility cycles through compact/path/status/all; render tests added, not run.
- [x] Interactive full-content toggle wraps complete commands, paths, and metadata; render tests added, not run.
- [x] Interactive raw rendering uses CRLF and wraps footer/help rows for narrow Windows terminals; tests pending.
- [x] Interactive run dialog supports instance count and original/current/custom cwd; launch-count test added, not run.
- [x] General `run` `-p/--run-path` alias is documented and has a parser test; not run.
- [ ] Locked JSONL migration, retention, and concurrent-writer work remains.
- [ ] Full automated verification and real non-default-cwd replay smoke test.
- [ ] User manual validation before Stage 4 commit.
