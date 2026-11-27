# Checklist

- [x] Milestone 1: immutable validated models, grouping/layout planner, tests, checkpoint.
- [x] Milestone 2: backend protocol, preview/result models, errors, fake backend contract tests, checkpoint.
- [x] Milestone 3: Windows Terminal capability and command builder, captured-process tests, checkpoint.
- [x] Milestone 4: docs, exports, package discovery/import checks, Ruff and diff review, final checkpoint.
- [x] Final worktree status and exact commit SHA recorded; no push or merge.
- [x] LLMD-40 follow-up: add and document a PowerShell 7 plan builder that requires a named target window.
- [x] LLMD-40 follow-up: qualify two PowerShell 7 launches to one unique named Windows Terminal window with child start/exit receipts.
- [x] LLMD-40 follow-up: test ProcWatch smart-mode handling for the default PowerShell 7 title without adding a global bypass.
- [x] LLMD-40 managed continuation: durable managed launch/pane IDs, positive spawn receipts, exit/failure receipts, and exact PID plus creation-time validation.
- [x] LLMD-40 managed continuation: concurrency, stale PID, partial launch, interrupted launch, spawn failure, and ownership-safe child shutdown regressions.
- [x] LLMD-40 managed continuation: live named-window PowerShell 7 tab qualification, all four requested pane layouts, UIA tab order inspection, and explicit unsupported geometry findings.
- [x] LLMD-40 managed continuation: provider-independent lifecycle/checkpoint and ProcWatch correlation contract documented; ProcWatch version bump removed.
- [x] Transactional correction: full-plan atomic reservation, one-time pre-spawn claims, conditional receipts, late-receipt preservation, and conservative recovery states.
- [x] Transactional correction: exact relay ownership and idempotent Ctrl+Break delivery, including the interrupted `delivering` state.
- [x] Transactional correction: pane-specific adaptive relay polling, deterministic regressions, and 1/5/20 native PowerShell child measurements.
- [x] Transactional correction: lifecycle and ProcWatch intentional-launch contracts updated; compatibility entry points retained.
- [x] Transactional correction: full validation, task-only review, and feature-branch commit/push.
- [ ] Independent GUI acceptance of the final correction SHA; then integrate and merge against refreshed `origin/main` under the standing authorization.
