# LLMD v2.1 Implementation Checklist

## LLMD-56 — standalone Claude Code provider (v2.1.0)

- [x] Add canonical Claude provider adapter and keep installation independent of local_agent_bridge, prepared resources, hooks, delegation infrastructure, and Terminal Launcher 0.2.0.
- [x] Support registration, exact attach/resume, start, switch, review/return, open, list/history, and explicit transcript-backed recovery.
- [x] Use an LLMD UUID with interactive `claude --session-id`; keep it reserved/pending until exact local transcript evidence is found; never auto-retry ambiguous starts.
- [x] Preserve identity and permission safeguards in managed native argv; reject alternate session IDs/resume/fork, background/print, alternate settings, cloud/desktop/worktree/teleport modes, and bypass controls.
- [x] Verify exact UUID resume, managed options, previews, Windows paths, missing executable, duplicate IDs, failed/interrupted initialization, pending recovery, provider switches, reviewer round-trip, and rebuild using deterministic fake providers and disposable registries.
- [x] Retain full Codex/AGY test coverage and test package installation without a bridge present.
- [x] Run module and compatibility suites, Ruff, package/version/help smoke, and diff checks; document source evidence vs simulated vs live qualification.
- [x] Commit/push the independently reviewable branch; await independent GUI acceptance before integration.

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
- [x] Commit and push task changes on the existing feature branch; do not merge.

## v1.5.2 correctness follow-up

- [x] Keep preview and pending launch on one resolved Windows/WSL environment with omitted and explicit selectors.
- [x] Stop post-exit options 4–6 from forwarding source cwd/native args without destination-specific confirmation.
- [x] Validate picker cwd before lifecycle changes and use expected-current CAS for historical `continue` and `switch -r`.
- [x] Require `switch -r -R` for inactive slots and reject completed slots.
- [x] Emit one JSON document for existing-session `start -j`; preserve text output.
- [x] Run focused and full module tests, scoped Ruff, version consistency, and diff checks.
- [x] Inspect cached main integration paths, commit, and push without merge/rebase.

## Batch G — Terminal-specific launch context (LLMD-27–29)

- [x] Add immutable launch-history events and a rebuildable terminal-scoped SQLite projection.
- [x] Record stable GUI/slot IDs, exact session/environment identity, launch/exit outcome, cwd provenance, Git context, and safe settings summaries.
- [x] Add `last`, JSON/history forms, exact-session resume and explicit inactive reactivation; add read-only `recent`.
- [x] Reject absent/malformed terminal IDs for scoped queries without global fallback; keep owner PID diagnostic only.
- [x] Cover terminal/pane concurrency, interrupted launches, post-exit switches, Windows/WSL, exact session resume, and persistence compatibility.
- [x] Run focused tests and full module tests with fake-provider isolation; update docs and checkpoint Batch G.

## Batch H — Comprehensive native CLI support (LLMD-30/31)

- [x] Make commonly used provider permissions, sandbox/approval, additional directories, model, reasoning, config, and profile options first-class managed settings.
- [x] Add explicit `--allow-native-unknown` for safe generic argv passthrough without weakening conflicts or permission preview.
- [x] Preserve exact session identity, fixed read-only bootstrap, provider-specific command order, and invocation-scoped settings.
- [x] Assess `open`/pane propagation and explicitly reject combinations that cannot be safely represented.
- [x] Cover managed validation, permissions preview, paths/quoting, provider ordering, WSL, failures, and no secret/raw config persistence.
- [x] Run focused/full tests, Ruff, installation smoke, version consistency, and diff checks; checkpoint Batch H without merging.

### Corrective review follow-up (LLMD-27–31)

- [x] Render requested GUI/agent/provider, exact native session, runtime, cwd provenance and Git repository/worktree/branch/commit; show unavailable values explicitly.
- [x] Give each terminal-launcher pane an isolated UUID context while keeping profile-owned terminal environment variables read-only.
- [x] Record launches only after command preflight and exact-session validation; distinguish unknown, interrupted, failed-spawn and abnormal-exit outcomes.
- [x] Require absolute additional-directory paths validated in the selected provider runtime.
- [x] Block recognized short/attached identity, help/version, cwd and execution aliases; document that authorized unknown flags cannot be semantically certified.
- [x] Run corrective focused and full module validation, Ruff, version consistency, and diff checks; commit/push and verify feature remote.
- [x] Preserve launcher-pane UUID context across post-exit options 4–6, reviewer return, and repeated transitions; verify consecutive launches stay pane-scoped.

## Deferred

- [ ] LLMD-25 persistent launch profiles (next planned batch).
- [ ] LLMD-26 native lock diagnostics (deferred).

## LLMD v1.6.0 integration candidate

- [x] Refresh main and feature refs; create a clean isolated candidate from current main.
- [x] Merge LLMD-27–31 without conflicts; preserve main's retired-tool removals and ownership/setup changes; retain the LLMD 1.6.0 registry entry.
- [x] Run agent_continuity, terminal_launcher, scripts_help, Ruff, version, and diff checks with provider calls mocked.
- [x] Verify disposable install, CLI version/help, terminal-scoped JSON history, native-argument preview, and projection rebuild compatibility.
- [x] Commit and push the integration candidate; verify remote SHA. No main merge authorized.

## Batch I — Semantic terminal presentation (LLMD-39)

- [x] Centralize semantic styles and fix exact-match styling after cell-aware padding.
- [x] Apply styles to listings, selectors, continuation picker, post-exit menu, history, last/recent, doctor, launch previews, and diagnostics.
- [x] Keep lifecycle, runtime observation, and launch outcome visually and textually distinct.
- [x] Implement cell-aware responsive layouts, group separation, empty-group and unresolved/pending identity labels.
- [x] Preserve `-c/--color auto|always|never`, `NO_COLOR`, terminal capability checks, redirected output, and ANSI-free JSON.
- [x] Propagate selected color mode through interactive entry, nested selectors, and provider-exit diagnostics; temporarily enable/restore VT for the actual Windows output console.
- [x] Test ANSI codes/resets, narrow/wide widths, Unicode/combining cells, long IDs, empty groups, selected history, and JSON purity.
- [x] Run captured-output tests and controlled PowerShell 7 smoke; separately report WSL/SSH availability and actual rendering limits.
- [x] Update README, CLI reference, implementation plan and STATUS; bump package and help-registry metadata to 1.7.0.
- [x] Run full module and relevant compatibility suites, Ruff, version consistency, and diff checks with fake-provider isolation.
- [x] Commit and push LLMD-39; pause for independent GUI acceptance before integration.
- [x] Correct LLMD-39 interactive color propagation and Windows console VT handling; bump package/help metadata to 1.7.1.

## LLMD v1.6.0 stable baseline

- [x] Merge LLMD v1.6.0 and LLMD-01–31 through PR #43; verify main baseline `93c0f29788fe57e56df124f699ebbd4116a7b6a8`.
- [x] Keep production installation unchanged; install smoke checks used disposable locations.

## LLMD v2.0.0 feature batch — LLMD-46/47 and LLMD-39 layout

- [x] Record action-default contract, `-d`/`-a` conflict rules, explicit `-N` replacement intent with compatible `-N -a`, latency stages, and responsive layout acceptance before code changes.
- [x] Make operational LLMD commands execute by default for existing-session/ordinary operations; retain `-a` alias and add explicit `-d` preview.
- [x] Keep read-only commands read-only; implement `last -r` with `last -a` compatibility.
- [x] Audit and migrate repository tests, examples, docs, and scripts that depended on implicit previews; inventory external callers.
- [x] Preserve inactive reactivation, historical selection, unknown-native authorization, ambiguity confirmations, and recovery safeguards.
- [x] Add monotonic startup stage timings, immediate flushed stderr progress, periodic blocking-stage updates, and redaction coverage without JSON stdout contamination.
- [x] Inspect installed Codex/AGY help and available source for exact-ID bootstrap alternatives; keep fixed read-only bootstrap absent verified evidence.
- [x] Optimize measured dispatcher overhead; report measured baseline/after values separately from targets.
- [x] Allocate listing columns from actual values; preserve complete UUIDs at 120 columns and stack before avoidable ID/timestamp clipping.
- [x] Update README, CLI reference, plan, status, checklist, help registry, and package metadata to v2.0.0.
- [x] Validate focused tests, full agent_continuity and compatibility suites, Ruff, disposable installation/smoke, version consistency, and diff checks with fake-provider isolation.
- [x] Commit and push the feature branch for independent GUI review; do not merge before review acceptance.

## v2.0.0 pre-review corrections

- [x] Repair focused regressions for execute-by-default lock validation and migrate preview-dependent tests to explicit `-d`.
- [x] Cover reviewer first-session initialization and explicit `review -N` replacement without mandatory `-a`.
- [x] Bound periodic startup progress to initialization and stop it before interactive provider handoff.
- [x] Reconcile active CLI reference text with the v2.0.0 contract while labeling prior release behavior as historical.
- [x] Run full module and relevant compatibility suites, scoped Ruff, version/help consistency, disposable-registry CLI smoke, and diff checks.
- [ ] Commit and push the correction candidate; await independent GUI review before integration or LLMD-56 implementation.
