# Runmux Web Explorer and Workspace Handoff

- Goal: implement RUNMUX-WEB-P3 without replacing the existing Runmux web UI.
- Branch/worktree: `codex/runmux-web-phase3-20261024` in
  `.worktrees/runmux-web-launch-20261024`.
- Base: merged Phase 2 at
  `bc2975c410c2f1eb71da9975d4fd27e8f895cfa9`.
- Specification: `docs/plans/web-ui-handoff/PHASE_03_EXPLORER_AND_WORKSPACE.md`.
- Plan and status: this directory's `00-implementation-plan.md`, `STATUS.md`,
  and `checklist.md`.
- Current finding: API responses intentionally omit argv, cwd, environment,
  supervisor credentials, and log paths. Preserve this privacy boundary.
- Next action: baseline browser screenshot, then test-first explorer controls
  using only supported list metadata. Keep all synthetic registry/process
  tests disposable. Do not begin Phase 4.
