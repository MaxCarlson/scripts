# Runmux Web Terminal and Log Correctness Handoff

- Goal: diagnose and repair proven defects in browser Output/Terminal fidelity
  (RUNMUX-WEB-P2); preserve the existing xterm.js WebSocket and input-lock
  design.
- Branch/worktree: `codex/runmux-web-phase2-20261024` in
  `.worktrees/runmux-web-launch-20261024`.
- Base: merged Phase 1 and `origin/main` at
  `97515f0905aa2cdc194cabd9c06a250d503256a3`.
- Specification: `docs/plans/web-ui-handoff/PHASE_02_TERMINAL_AND_LOG_CORRECTNESS.md`.
- Plan: `00-implementation-plan.md`; current status: `STATUS.md` and
  `checklist.md`.
- Findings and fixes: Output merged CR progress rewrites; its history policy now
  normalizes CRLF/lone CR while Terminal keeps raw bytes. “Jump to latest”
  resumes Follow. Headless Chromium exposed xterm styles blocked by shared CSP;
  Runmux now opts into style attributes/rules without allowing inline scripts.
  POSIX `TIOCSWINSZ` updated dimensions but did not signal the detached child;
  supervisor now delivers SIGWINCH to the process group. Test and browser fixture
  verify redraw from 80x24 to 137x34 under the existing input lock.
- Validation: 39 focused Runmux tests and 8 web_ui_tools tests pass in WSL;
  Ruff, dashboard JS checks and `git diff --check` pass. Clean headless Chromium
  visually verified synthetic Manga-style and file-util-like screens, ANSI
  styles, progress cursor updates, long paths, inert markup, resize/redraw and
  cleanup. Windows pytest and a standalone event-loop probe stall in Proactor
  self-pipe creation. Windows ConPTY resize after the fix and Linux glyph
  rendering remain unverified; bounded tail cannot recreate omitted TUI history.
- Next action: push this branch without merging. Do not begin Phase 3.
