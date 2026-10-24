# Browser Process Launching Handoff

- Goal: deliver Runmux Web P0 process launching (L01–L09).
- Branch/worktree: `codex/runmux-web-launch-20261024` at
  `.worktrees/runmux-web-launch-20261024`, based on `origin/main`
  `6cbf599a8c5e51839f742c02876d035efefbca36`.
- Decisions: reuse `create_managed_run`; pass argv directly; show the web
  server's startup directory as the default; require the existing authenticated
  same-origin browser session for launch.
- Changed paths: `src/runmux/web.py`, `src/runmux/cli.py`, the dashboard HTML,
  CSS, and JS, `tests/web_test.py`, `tests/dashboard_test.js`, package metadata,
  README/handoffs, the master roadmap, supplied gap analysis/image, and this
  plan folder.
- Verification: see `STATUS.md` for focused test results, browser smoke, package
  metadata checks, the reproduced origin/main suite failures, and the missing
  Hatchling build dependency.
- Remaining work: final diff/status check, commit, and push this branch. Do not
  merge.
