# Phase 2 Checklist

- [x] Reproduce ordinary text, carriage-return progress, ANSI color, and Unicode
  with a synthetic supervised process; compare raw log, API, Output, and
  Terminal rendering.
- [x] Identify one confirmed defect in the Output browser presentation layer:
  preserved carriage returns were concatenated visually.
- [x] Add regression tests that fail against the diagnosed Output and follow
  behavior defects, then verify both pass after focused fixes.
- [x] Apply the minimal Output normalization and Jump to latest follow-state
  fixes while preserving raw Terminal bytes and supervisor input-lock behavior.
- [x] Verify byte/log/API behavior, bounded output, follow-tail, truncated
  terminal replay, finished-run WebSocket replay, and inert browser text
  handling as applicable.
- [x] Add a dashboard check that retained Output history stays within 512 KiB.
- [x] Exercise dimension-sensitive TUI behavior through the browser. Confirm
  input-lock-gated POSIX PTY resize and fix SIGWINCH delivery to the child.
- [x] Diagnose and fix xterm ANSI styling blocked by the default shared-app CSP
  using a Runmux-only style opt-in; keep inline scripts blocked.
- [x] Run final WSL Python tests (39 Runmux, 8 web_ui_tools), Ruff, dashboard
  JavaScript checks and whitespace check.
- [x] Verify post-fix behavior in clean headless Chromium with disposable
  synthetic processes; inspect Manga-style and file-util-like Terminal views.
- [x] Record platform limits: Windows Proactor self-pipe hang; Windows
  ConPTY resize not revalidated after fixes; WSL image lacks Unicode fonts;
  bounded replay cannot recreate missing terminal history.
- [x] Update Runmux documentation and roadmap status with findings and limits.
- [x] Commit, push, and fast-forward merge Phase 2 into `main` at
  `bc2975c410c2f1eb71da9975d4fd27e8f895cfa9`.
