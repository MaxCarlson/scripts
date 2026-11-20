# Status — Named Agent Dispatcher

- **Scope:** Named GUI conversations and agent slots, durable activation history, shared `llmd` / `llm-dispatcher` CLI, interactive navigation, provider launch supervision, and `terminal_launcher` API integration.
- **Branch:** `integration/llmd-terminal-launcher-verified-20261119`
- **Worktree:** `../../../../.worktrees/integration-llmd-terminal-launcher-verified-20261119`
- **Base:** `0d4b5227b3b699345c1ac366fc1e4da823e6d944` (merge of dispatcher and terminal-launcher feature branches)
- **Approval:** Implementation and checkpoint commits authorized by the user handoff; no push or merge authorized.
- **Current stage:** Integration validation and checkpoint commit complete.
- **Next action:** Keep this branch as the merge-ready integration candidate. Any main merge, push, and real Windows Terminal smoke test require separate authorization.
- **Constraints:** Preserve the event spool as source of truth and the existing `agents` CLI. Do not install hooks, run paid provider sessions, launch live Windows Terminal panes, alter global Terminal settings, push, or merge to `main`.
- **Integration status:** M2 is integrated. The dispatcher maps active slots into `PaneSpec` and delegates grouping, previews, and submission to `terminal_launcher`; no Windows Terminal commands are constructed in `agent_continuity`.
- **Feature commits:** Dispatcher `db8d5779b1382627e804b04db86bea0036aa35fd`; terminal launcher `6ce150d29fd6e6a961e0fd8e8e6a828ee409b5d1`. The existing integration ancestry is `c5380df9` then `0d4b5227`; the common base is `f57b22652dfc8cd67823a2a0d1d2792b3f09a320`. Both merges had already been recorded before this validation branch; no merge conflicts were resolved in this run.
- **Selection ordering:** Active slots are ordered by verified activity descending, with the stable slot-name ordering from the dispatcher query used for ties. The backend preserves this order in panes and composite tab titles.
- **Layout checks:** Default two-pane grouping gives two slots one split tab and four slots two split tabs. `-k 4` gives up to four panes in one tab; `-k 3` yields the library's large-left/two-stacked-right layout. Captured command tests verify composite titles, window targeting, cwd and argument-preserving relay payloads including spaces, semicolon and Unicode.
- **Backend error handling:** Backend results serialize as structured JSON. A rejected Terminal request returns exit code 1; interactive Open All reports rejection without claiming pane startup. Empty unresolved-only plans preview without requiring `wt.exe`.
- **Correlation status:** M2 `HOOK_EVENT` records identify provider, environment, session, and hook type but do not contain the dispatcher `launch_id`. Concurrent pending launches therefore cannot be deterministically correlated. Manual attachment remains the safe recovery path.
- **Ruling:** Use a new verification worktree from the committed two-branch merge because the pre-existing integration worktree acquired concurrent uncommitted edits during validation — this isolates our changes and leaves those edits intact — if wrong, that separate work may need an explicit later reconciliation.
- **Validation:** `agent_continuity` 77 passed; `terminal_launcher` 41 passed; `scripts_help` 55 passed; `runtime_lifecycle` 58 passed; `snips` 34 passed, 1 skipped because of Windows process sandbox denial (WinError 623). Ruff, compile checks, and `git diff --check` passed.
- **Packaging:** Built wheels for `agent-continuity` 1.1.0 and `terminal-launcher` 0.1.1, installed together in a disposable venv, and passed `pip check`, API import, all three CLI `--help` checks, and JSON GUI-list smoke.
- **Remaining acceptance:** No real Windows Terminal launch was authorized, so pane geometry and child startup remain unverified. No Codex/AGY sessions or hooks were used. The original integration worktree and its concurrent uncommitted files were preserved.
