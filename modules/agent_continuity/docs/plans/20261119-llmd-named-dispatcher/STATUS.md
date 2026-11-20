# Status — Named Agent Dispatcher

- **Scope:** Named GUI conversations and agent slots, durable activation history, shared `llmd` / `llm-dispatcher` CLI, interactive navigation, provider launch supervision, and `terminal_launcher` API integration.
- **Branch:** `feature/llmd-agent-dispatcher-20261119`
- **Worktree:** `../../../../.worktrees/llmd-dispatcher-20261119`
- **Base:** `f57b22652dfc8cd67823a2a0d1d2792b3f09a320` (M2 merge already integrated)
- **Approval:** Implementation and checkpoint commits authorized by the user handoff; no push or merge authorized.
- **Current stage:** Dispatcher implementation complete; final regression and packaging validation.
- **Next action:** Finish regression/package checks, inspect and commit the task-only diff. The `terminal_launcher` package is a separate workstream and is absent from this branch.
- **Constraints:** Preserve the event spool as source of truth and the existing `agents` CLI. Do not implement terminal layout/backend logic, install hooks, run paid provider sessions, alter global Terminal settings, push, or merge.
- **Integration status:** M2 is already integrated at base `f57b22652dfc8cd67823a2a0d1d2792b3f09a320`. CLI integration emits `PaneSpec` values and delegates grouping/launching to `terminal_launcher`; real terminal execution remains unverified until that package is integrated.
- **Provider status:** Provider CLI syntax was read from installed help. No provider sessions were started; live native session-ID correlation is pending and exact IDs can be attached explicitly.
- **Validation:** `agent_continuity` 66 passed; `scripts_help` 55 passed; `runtime_lifecycle` 58 passed; `snips` 34 passed, 1 skipped by the Windows process sandbox (WinError 623). Ruff, `compileall`, CLI entry-point help, JSON list smoke, and `git diff --check` passed.
- **Packaging:** Built and installed `agent-continuity` 1.0.0 in a disposable venv; `llmd --help`, `llm-dispatcher --help`, and `agents --help` all exited 0.
- **Remaining acceptance:** `terminal_launcher` is not present in this checkout, so tab/pane launch and live Windows Terminal integration are pending the separate package. No Codex/AGY session was launched; automatic session-ID correlation and live hook behavior remain unverified.
