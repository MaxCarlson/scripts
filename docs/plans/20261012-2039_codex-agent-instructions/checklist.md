# Checklist

Plan created: 2026-10-12 20:39 -07:00
Last updated: 2026-10-12 21:57:29 -07:00
Full plan completed: pending

- [ ] Stage 1 - repository routing implemented; user review pending
- [x] Stage 2 - global Codex policy source and symlink target verified; fresh Codex runtime loading check blocked by sandbox access
- [ ] Stage 3 - nested guidance and handoff implemented; review and runtime loading check pending
- [ ] Stage 4 - Claude parity and Gemini repository routing implemented; Claude symlink target verified; Gemini runtime and global loading checks pending
- [ ] Local GPU helper feasibility, longer-term investigation

## Stage 1 features

- [x] Root `AGENTS.md` routes reads by task and keeps safety rules clear - implemented and verified.
- [x] Repo guide states one commit approval boundary and narrows routine reading - implemented and verified.
- [x] Root handoff and plans index identify this plan without misstating earlier work - implemented and reviewed.
- [x] Changed paths and whitespace verified - `git diff --check` passed.
- [ ] Fresh Codex root-session instruction check; CLI attempt was blocked before session startup by sandbox access to Codex state/temp files.
- [x] User authorized commit, push, and merge into `main`.

## Stage 4: Claude parity follow-up

- [x] Confirm the dotfiles global Claude instruction source already matches Codex policy, with one Claude-specific permissions reminder.
- [x] Reduce the scripts root Claude entry point to the canonical root `AGENTS.md` import.
- [x] Replace the ignored `.claude/CLAUDE.md` policy with a comment-only pointer to the canonical root instructions.
- [x] Verify root entrypoint and global symlink source selection; whitespace and repository state checks passed.
- [x] User authorized publishing the reviewed instruction changes.
- [x] Root `GEMINI.md` imports canonical `AGENTS.md` using official Gemini CLI import syntax.
- [ ] Verify root and nested context discovery in a fresh Gemini CLI session.
- [ ] Verify global Gemini source and active link status; not included in this Codex/Claude symlink check.

## Stage 3: Nested guidance and module routing

- [x] Root `AGENTS.md` and `REPO_LLM_INSTRUCTIONS.md` tell agents starting in `scripts/` to read only the target module's nested instructions before editing.
- [x] State clearly that module-owned plans and handoffs stay in the module's `docs/`, while shared work uses `scripts/docs/`.
- [x] Add concise `modules/runmux/AGENTS.md`; reduce `modules/runmux/docs/AGENTS.md` to a redirect.
- [x] Replace stale aebndl path and upstream Git workflow rules with module-scoped guidance.
- [x] Verify instruction paths and staged/unstaged whitespace.
- [ ] Fresh Codex session verifies nested module guidance is read when launched from a representative path; the CLI attempt was blocked before session startup by sandbox access to Codex state/temp files.
- [x] With the repo `.venv`, aebndl focused pytest gets past `tqdm` but collection is blocked by sibling-module `tests.conftest` import mismatch; limitation recorded.
