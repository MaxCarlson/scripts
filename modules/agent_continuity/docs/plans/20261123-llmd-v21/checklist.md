# LLMD v2.1 Implementation Checklist

## Batch A — Session safety and lifecycle

- [x] Unify positional and named `start` validation/preview/apply behavior.
- [x] Auto-create missing GUI/slot idempotently for both forms.
- [x] Preserve explicit `-N -a` authorization and duplicate-session prompts.
- [x] Revalidate launch state atomically; protect pending and concurrent starts.
- [x] Add bidirectional post-exit provider switching without slot/history loss.
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
- [x] Cover Codex/AGY, different worktrees, interruption/cancel/abnormal-exit paths.

## Final

- [x] Run focused module tests after each sequential batch; repair failures before advancing.
- [x] Run requested broad module suite (159 passed), Ruff, version consistency, and diff checks.
- [x] Review task-only diff and final branch status.
- [x] Commit and push the implementation branch; do not merge.
