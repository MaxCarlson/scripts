# Clipboard compare commands status

## Goal

Provide concise clipboard-vs-file comparison as `cld`, preserve the existing full diff as `cldd`, and add pairwise file comparisons as `comp` / `compd`, including `fd` results.

## Branch and worktree

- Branch: `codex/clipboard-compare-commands-20261127`
- Worktree: `C:\Users\mcarls\.codex\worktrees\clipboard-compare-commands\scripts`
- Base: `origin/main` at `fd37f654`

## Decisions

- Reuse `compare_texts` and its normalized-by-default / strict comparison semantics.
- Report decoded Unicode character counts, matching the existing `ComparisonResult` metrics.
- Keep the old `pyscripts/clipboard_diff.py` implementation and snapshot behavior unchanged behind `cldd`.
- Expand `fd` NUL-delimited output into a path list in-process; no CSV intermediate is needed.
- `compd` prints unified diffs for every pair, then the concise summary table; it does not read or modify the clipboard.

## Progress

- [x] Add regression coverage for comparison helpers and all four CLI behaviors.
- [x] Implement new commands and preserve old `cldd` dispatch.
- [x] Update package version and user-facing help/docs.
- [x] Run focused clipboard module tests and review the task-only diff.
- [ ] Commit and push the feature branch; merge only if authorized for this change.

## Remaining work

Commit and push the verified feature branch, then report exact invocation syntax and how each checkout can install and verify the commands.
