# Status

- Branch: `codex/ytaedl-priority-file-queue-20261106`
- Worktree: `.worktrees/ytaedl-priority-file-queue-20261106`
- Base: `86c106bc2176e16a9646df3f8ed7c802bf927fb1`
- State: implementation and validation complete; ready for integration review.
- Behavior: exact-mode worker slots are capped by `-t`; overflow files remain
  queued. `--priority-file-scheduling file` (default) processes a selected file to completion before
  moving on; `-pf url` rotates URL assignments across selected files through a
  private in-memory domain index.
- Validation: `pytest -q` — 408 passed, 1 skipped, 1 unrelated known failure in
  `tests/bug_fixes_and_features_test.py::TestShowBarsRemoved::test_show_bars_not_in_parser`;
  after the final focused addition, `pytest -q -k "not test_show_bars_not_in_parser"`
  — 409 passed, 1 skipped, 1 deselected. Focused scheduling tests — 6 passed.
  `ruff check` and
  `compileall` passed; `git diff --check` passed.
- No media download or live service was used. No commit, merge, or push has
  been performed.
