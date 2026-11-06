# Status

- Branch: `codex/ytaedl-priority-file-queue-20261106`
- Worktree: `.worktrees/ytaedl-priority-file-queue-20261106`
- Base: `86c106bc2176e16a9646df3f8ed7c802bf927fb1`
- State: review corrections implemented and validated; ready for feature-branch commit/push.
- Review findings addressed: `-H` now bounds initial/runtime worker slots while
  `-t` requests initial workers; `-pf/--priority-file-scheduling` parses both
  `file` and `url`; URL mode retries idle workers periodically and keeps queued
  or in-progress index work from triggering automatic exit; incomplete whole-file
  assignments get one in-session retry and are durably retained for restart.
- URL-mode source-file exclusivity remains intentional for lock and duplicate
  safety. It limits simultaneous assignments to the number of eligible source
  files. Idle workers retry after locks or domain slots become available.
- Corrected-code validation: `pytest -q -k "not test_show_bars_not_in_parser"`
  — 415 passed, 1 skipped, 1 deselected; manager tests — 89 passed; domain-index
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
