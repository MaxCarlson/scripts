# LLMD v2.1 Implementation Checklist

## Batch A — Session safety and lifecycle

- [x] Unify positional and named `start` validation/preview/apply behavior.
- [x] Auto-create missing GUI/slot idempotently for both forms.
- [x] Preserve explicit `-N -a` authorization and duplicate-session prompts.
- [x] Revalidate launch state atomically; protect pending and concurrent starts.
- [x] Add bidirectional post-exit provider switching without slot/history loss.
- [x] Revalidate option-4 current activation under lock; inherit/restore exact native environment and cwd; return to exit menu after cancellation.
- [x] Validate normal exits and cancellation with fake providers; full abnormal/captured-pending coverage remains in module suite.

## Batch B — CLI presentation and history

- [x] Align interactive selector columns across ANSI, Unicode, and resize cases.
- [x] Add local GUI/agent timestamps, provider/status colors, and GUI separators.
- [x] Implement compact width-aware terminal rendering and runtime status.
- [x] Add `list -N/--history-count` for scoped/global text and JSON output.
- [x] Print one fresh scoped listing after lifecycle/switch resolution.
- [x] Verify JSON compatibility, completed filtering, and activation history.

## Batch C — CLI simplification

- [x] Improve public help and omit internal `pane-run` from ordinary help.
- [x] Audit callers before any administrative command change; retain compatibility.
- [x] Update README and CLI reference for all shipped behavior.

## Batch D — Reviewer handoff and return

- [x] Persist original/reviewer relationships and review cycle events/projection.
- [x] Implement `review` resume/new flow and exact `-N -a` authorization.
- [x] Implement `return` plus context-aware post-exit return action.
- [x] Prevent duplicate sessions/slots and stale/concurrent transitions.
- [x] Review inactive originals without lifecycle/session loss; explicit return reactivates the exact original session.
- [x] Cover Codex/AGY, different worktrees, interruption/cancel/abnormal-exit paths.

## Final

- [x] Run focused module tests after each sequential batch; repair failures before advancing.
- [x] Run requested broad module suite (170 passed), Ruff, version consistency, and diff checks.
- [x] Review task-only diff and final branch status.
- [x] Commit and push the corrective changes on the implementation branch; do not merge.

## Batch F — Native launch customization (LLMD-22–24)

- [x] Verify installed Codex resume and AGY CLI help; record allowlisted native flags and provider-specific ordering.
- [x] Parse argv after `--` for start, continue, switch, review, and return; reject identity, execution, bootstrap, and directory conflicts.
- [x] Add invocation-scoped `-C/--cwd` validation for local and recorded WSL environments; surface repository/worktree changes without rewriting session cwd provenance.
- [x] Add pure launch previews with executable/argv, cwd, environment, exact session, requested permissions, and explicitly unverified effective settings.
- [x] Keep overrides out of fixed read-only bootstrap and apply them only to exact-ID interactive resume.
- [x] Explicitly reject unsupported open/terminal-pane native overrides.
- [x] Harden every module test against real provider subprocesses with fake provider discovery and an argv/process guard.
- [x] Cover quoting, spaces, repeatable flags, conflicts, Windows wrappers, WSL, previews, failed launches, and preserved session/history identity.
- [x] Update README, current CLI reference, feature register, module version, and deferred LLMD-25/26 status.
- [x] Run focused tests, full module suite, Ruff, and diff checks; inspect integration risk against main without merge/rebase.
- [ ] Commit and push task changes on the existing feature branch; do not merge.
