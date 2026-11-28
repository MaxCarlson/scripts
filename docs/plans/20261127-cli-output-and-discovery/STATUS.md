# CLI Comparison and Command Discovery Status

## Goal

Implement the compare output improvements, general `flatten` filter, and metadata-driven ag views described in the handoff.

## Branch and worktree

- Branch: `codex/clipboard-format-flatten-views-20261127`
- Worktree: `C:\Users\mcarls\.codex\worktrees\clipboard-compare-commands\scripts`
- Base: `c8febf3d5bcad76613f1b33c922ac3d5db3f175e` (handoff commit; code baseline `8e6fb41`)

## Decisions

- Follow explicit row-limit, CSV, and view scope details in the user's pasted request.
- Use explicit alias metadata, not name-length inference.
- Treat `-n 0` as show all; comparisons still evaluate every pair.
- The user confirmed `fg` is a useful command name in their Bash/Zsh setup. The managed POSIX adapter defines the requested function to select the full command view.
- No PATH mutation and no merge.

## Progress

- [x] Read user-provided specification and inspect current repo state.
- [x] Create task branch and write implementation plan.
- [x] Add regression tests and implement pairwise output changes.
- [x] Add and test `flatten` CLI.
- [x] Add metadata-driven ag views and shell adapter support.
- [ ] Run final focused tests, review diff, commit and push branch.

## Verification notes

- Compare plus flatten focused tests: 30 passed.
- scripts_help registry/view tests: 14 passed.
- scripts_help CLI tests: 44 passed.
- Python compile checks passed.
- A broader clipboard module test collection was attempted but stopped during collection because the environment lacks the existing `cross_platform.clipboard_utils` package; this is an environment prerequisite, not a failure in the changed compare tests.
- The root repository setup bootstrap tests were also attempted and two failed because they expected venv re-execution calls that the current environment did not perform; those tests do not cover these changes.
