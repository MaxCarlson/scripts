# Phase 00 — Baseline Reconciliation and Integration Gate

## Recommended model: GPT-6 Luna — High

**Priority:** P0 • **Role:** Single repository reconnaissance/integration owner • **Depends on:** nothing • **Mutations:** documentation/checkpoint only; no functional source changes • **Next:** Phase 01 once stop-command dependency is settled

### Objective

Establish what has actually been committed, validated, assigned, and merged before touching Monitor lifecycle. Avoid duplicate work on `llm-monitor web stop`, conflicting worktrees, and stale architecture assumptions. Freeze the cross-module contracts in `CONTRACTS.md` or amend them based on observed source.

### Verified planning inputs

The 2026-11-02 GitHub `main` snapshot of `modules/llm_monitor/llm_monitor/cli.py` still exposed foreground `web` without `web start/status/stop/restart`; `web.py` printed the banner before `server.run()`. `modules/runmux/src/runmux/server_lifecycle.py` contains owner-protected descriptor and signed lifecycle primitives. `agent_benchmark/suite_monitor.py` accepts cookie env/file bootstrap. The text supplied by the user reports **another agent implementing the stop command** and benchmark preflight passing. Do not assume these observations remain true in the local checkout or after independent agent completion.

### Required read-only discovery

1. Enumerate repository root, branch, remotes, commits, local status, untracked files, worktrees, and latest verified agent checkpoints (`git status --porcelain=v1`, `git branch -vv`, `git worktree list --porcelain`, `git log --all -n 20 --oneline`). Respect Windows/WSL path and sandbox constraints; do not retry blocked Git operations in the same context repeatedly.
2. Inspect recent PRs and `STATUS.md` ledgers for Monitor lifecycle, agent-benchmark suite, Runmux web server, recorder durability, and OpenCode v2 adapter. Record explicit status categories: `unassigned`, `active`, `committed`, `validated`, `merged`, `unknown`. Remote branch visibility alone does not prove an agent is active.
3. Identify **owner of `llm-monitor web stop`** and current workspace/files. If active, do not edit overlapping files. If complete, inspect its diff, test logs and validated SHA; reuse the implementation and preserve its API where reasonable. If incomplete but inactive, document safe continuation or integration gate; do not invent permission to overwrite.
4. Inspect exact parser contracts for `web`, `suite plan/run/resume`, `-F`, `-x`, `-R`, Host/Origin, login sessions, recording status and gateway readiness. Inventory run manifest schema and essential evidence artifacts. Capture Python versions/dependency entry points, lockfiles, supported platforms and test baselines.
5. Review `server_lifecycle.py` for minimum safe reusable primitives. Favor copy/adapt of **principles**, not cross-module runtime import dependency unless stable/public and tested. Note owner ACL limitation, reparse handling, Windows child process topology and socket pre-binding pattern.
6. Reconcile default port from actual code (GitHub snapshot: 8788) with desired example port (8789). Decide whether no-argument `llm-monitor web` remains a compatibility alias to foreground `web start` and how existing scripts interpret `web -p`.
7. Freeze `CONTRACTS.md` version, schema, compatibility and CLI decisions; produce an explicit ownership plan for Phases 01–04. Do not modify preexisting work without proving isolation.

### Exit artifacts

Create/update a phase `STATUS.md` containing: exact repo/worktree paths, dirty state (with no sensitive contents), active assignment matrix, merge/validation SHA(s), test command/exit-log paths, stop-command status, contract differences, and branch/worktree choice for Phase 01. Mark unknown information `unverified`; never synthesize successful tests. Add a `BASELINE.md` to the repository's chosen plan directory if practical and only after checking collisions. Do not push/merge unless authorized.

### Acceptance criteria

- No active worktree or source file modified by this phase.
- Stop-command integration path is explicit and nonduplicative.
- Parent/child topology, port, auth/cookie, recording/manifest constraints and new CLI surface are mapped to actual current code.
- Latest validated dependency commit is identified, not assumed to be `main`.
- Phase 01 has a branch ownership decision and no unresolved conflicting source edits.

### Required final report

State observed vs unverified facts; exact checkpoint SHA and current dirty status; changes to proposed contracts; blockers whose remedy requires user action; whether Phase 01 is unblocked. Do **not** request an arbitrary confirmation for ordinary reversible design choices. If stop work is in progress, recommend waiting for its checkpoint rather than reimplementing its functionality.
