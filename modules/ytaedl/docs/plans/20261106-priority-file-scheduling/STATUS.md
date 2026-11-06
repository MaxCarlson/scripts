# Status

- Branch: `codex/ytaedl-priority-file-queue-20261106`
- Worktree: `.worktrees/ytaedl-priority-file-queue-20261106`
- Base: `86c106bc2176e16a9646df3f8ed7c802bf927fb1`
- State: scheduler corrections validated; feature branch remains unmerged pending explicit approval.
- Previous correction commit: `24582d1a9a2e8a9da93d5d2516295d70d694d93f`.
- Review findings addressed: `-H` now bounds initial/runtime worker slots while
  `-t` requests initial workers; `-pf/--priority-file-scheduling` parses both
  `file` and `url`; URL mode retries idle workers periodically and keeps queued
  or in-progress index work from triggering automatic exit; incomplete whole-file
  assignments get one in-session retry and are durably retained for restart.
- Restored exact-mode file submissions are matched to explicit files by resolved,
  case-normalized paths. Matching pending queue entries are claimed by the
  explicit initial/overflow assignment, and an active source path cannot be
  assigned to a second whole-file worker.
- URL-mode source-file exclusivity remains intentional for lock and duplicate
  safety. It limits simultaneous assignments to the number of eligible source
  files. Idle workers retry after locks or domain slots become available.
- Corrected-code validation: `pytest -q -k "not test_show_bars_not_in_parser"`
  — 418 passed, 1 skipped, 1 deselected; manager tests — 92 passed; focused
  restored-submission cases — 3 passed; domain-index
  tests — 28 passed; runtime-submission tests — 11 passed. Ruff, compileall,
  CLI help (`python -m ytaedl.manager --help`), and `git diff --check` passed.
- `DomainIndex.pick_url()` synthetic median selection latency: 1k URLs 2.758 ms,
  10k 3.753 ms, 50k 11.505 ms (seven selections per size, twenty files and
  forty domains). No selector optimization was justified by these results.
- The pre-existing unrelated assertion
  `tests/bug_fixes_and_features_test.py::TestShowBarsRemoved::test_show_bars_not_in_parser`
  remains excluded; it failed on the previous implementation as well.
- No media download or live service is used. The preserved review patch is
  unmodified; integration into `main` remains gated on explicit approval.
