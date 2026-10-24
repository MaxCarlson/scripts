# Runmux Web Terminal and Log Correctness Status

Updated: 2026-10-24

## Current state

Phase 2 implementation and focused validation are complete on
`codex/runmux-web-phase2-20261024`, based on merged Phase 1 / `origin/main` at
`97515f0905aa2cdc194cabd9c06a250d503256a3`. Synthetic fixtures modeled on the
supplied MangaDL and file-util screenshots were used; installed applications
and real user data were not launched.

## Verified source flow

- Child processes are supervised; output is appended to `output.ansi` by the
  platform-specific PTY/ConPTY/pipe pump.
- Output reads bounded bytes, incrementally decodes UTF-8, strips terminal
  control sequences and carries parser/cursor state across HTTP polls.
- Terminal reads bounded raw ANSI bytes from the same log, sends binary WebSocket
  frames with acknowledgements, and renders through the existing xterm.js.
- Browser Output is appended as inert `textContent` and capped at 512 KiB.
- Browser terminal resize is sent only while the supervisor grants the
  attachment input lock.

## Findings and fixes

- **Output view:** Raw Windows `output.ansi` preserved CRLF, literal CR progress
  rewrites, ANSI and UTF-8. The history API removed ANSI but passed carriage
  returns through, so browser Output merged successive progress updates. The
  history view now normalizes CRLF and lone CR to line breaks, including CR
  split across API chunks. Terminal still receives unchanged raw bytes and
  interprets CR as cursor movement. This is an Output presentation defect, not
  corruption in capture or storage.
- **Terminal ANSI styles:** A clean headless Chromium profile showed CSP
  `style-src 'self'` violations from xterm's dynamically inserted style rules;
  ANSI cyan and dim styling were absent. `web_ui_tools` now supports an
  explicit opt-in style policy, enabled only by Runmux; scripts remain
  restricted by `script-src 'self'`. Post-fix browser screenshots show cyan
  MangaDL-like output and dim file-util-like entries, with no style CSP errors.
- **POSIX PTY resize:** A live synthetic file-util-like TUI started at 80x24.
  Browser fit measured 137x34. Before the fix, supervisor registry dimensions
  changed but the child logged only `redraw=0`: the detached POSIX child had a
  PTY but no controlling terminal, so `TIOCSWINSZ` did not deliver SIGWINCH.
  `SupervisorState.resize` now signals the child's process group after ioctl.
  A test-first regression and browser fixture show `RESIZE:131x41` / `redraw=1`;
  the rendered list changed from two to three columns. Resize remains gated on
  the supervisor input lock.
- **TUI reproduction:** Synthetic Manga-style progress and file-util-like
  multi-column/long-path screens were exercised in actual xterm.js Terminal,
  at recorded viewport/PTY sizes, with clean headless Chromium. ANSI color,
  cursor-updated progress, safe inert `<script>` text, and resize/redraw were
  visually inspected. This establishes representative stream behavior, not the
  original binaries' internal terminal behavior.
- **Replay:** Terminal WebSocket replays a bounded raw tail. If that tail starts
  after control sequences that built the current screen, the browser cannot
  reconstruct the missing frame. The UI now warns that the historical screen
  may be incomplete; unavailable history is not synthesized.

## Changes so far

- Added a failing-then-passing dashboard regression for CRLF and lone-CR
  normalization across API chunk boundaries. The history-oriented Output view
  now converts both to line breaks; Terminal remains raw and xterm.js continues
  to interpret carriage returns as terminal cursor movement.
- Added a failing-then-passing follow-tail regression. “Jump to latest” now
  scrolls to the end and re-enables Follow after the user scrolls upward.
- Added coverage that the dashboard history remains capped at 512 KiB.
- Added a synthetic WebSocket test proving TUI cursor, erase, and alternate
  screen sequences remain byte-for-byte intact, including for an already
  finished process without creating a supervisor attachment.
- Added bounded-tail coverage demonstrating that replay can begin within an
  ANSI sequence, and changed the Terminal notice to explain that this screen
  may be incomplete. The current behavior does not reconstruct missing screen
  history.
- Added a POSIX integration regression for SIGWINCH delivery and a scoped CSP
  opt-in for xterm.js styles, with shared-app tests proving inline scripts
  remain blocked by default and in the opt-in policy.

## Phase 2 P0 acceptance status

| Requirement | Evidence and status |
|---|---|
| Ordinary logs, CR progress, ANSI and UTF-8 | Windows synthetic capture and focused tests; Output CR normalization verified. |
| ANSI/cursor/erase Terminal rendering | Synthetic WebSocket byte-preservation test and post-fix headless Chromium screenshots; pass for exercised sequences. |
| Unicode wide glyphs and emoji | Windows synthetic capture and earlier Windows browser rendering preserved UTF-8. WSL Chromium lacks required glyph fonts and shows boxes; current Linux visual glyph layout remains unverified. |
| Long lines/paths and safe rendering | Headless file-util-like Terminal showed long paths without app-level overflow; literal `<script>` remained inert. |
| Resize and redraw | WSL POSIX PTY regression and browser-controlled 80x24 → 137x34 resize/redraw pass. Real Windows ConPTY resize was not visually validated after fixes. |
| Sustained output, bounded history, reconnect | Existing 512 KiB Output, bounded WebSocket replay/ack, and reconnect tests pass. An arbitrary truncated tail cannot recreate a prior screen; warning is explicit. |
| Completed/lost process history | Existing retention/replay tests pass; available history remains bounded by persisted output and configured tail. |
| Follow and display-only behavior | Dashboard follow/resume regression passes; browsing does not pause the child. Resize/input remains supervisor-lock protected. |
| No real user state mutation | All live browser fixtures used disposable synthetic registries/processes and were stopped after capture. |

## Validation

Fresh final WSL validation on 2026-10-24:

- `PYTHONPATH=src:../web_ui_tools/src /home/mcarls/scripts/.venv/bin/python -m pytest tests/web_adapter_test.py tests/web_test.py tests/supervisor_test.py -q` in `modules/runmux/` — 39 passed.
- `PYTHONPATH=src /home/mcarls/scripts/.venv/bin/python -m pytest tests/test_app.py -q` in `modules/web_ui_tools/` — 8 passed.
- Ruff over changed Python source/tests — all checks passed.
- `node tests/dashboard_test.js`, `node --check src/runmux/web_static/assets/dashboard.js`, and `git diff --check` — passed.
- Clean headless Chromium / Playwright, viewport 1366x768, empty disposable registry then synthetic launches: verified empty UI, Manga-style ANSI/cursor progress, file-util-like ANSI/multi-column/long-path output, control-lock resize/redraw, safe text, and process cleanup. Screenshots are in ignored `.pytest_tmp_root/phase2_headless_*` artifacts.
- Windows focused pytest and a standalone `asyncio.new_event_loop()` probe both stalled in Windows Proactor self-pipe creation (`socket.accept` in `_fallback_socketpair`) before TestClient startup. This bounded diagnosis identifies an environment-level event-loop failure; the Windows rerun is not counted as passing. Windows ConPTY resize after fixes is not claimed.
- The available public WSL package index lacked `resource-metrics`, so unrelated stats tests were not run. Focused suites used the existing WSL venv and did not import that package.

The real MangaDL/file-util executables and user registries were not touched.
Unicode screenshot limits are due to fonts in the WSL headless image, not
evidence of a Runmux transport defect. The Phase 2 P0 behavior is covered for
the supported synthetic flows, subject to the explicitly unverified Windows
ConPTY resize and Linux glyph rendering above.

## Delivery

Merged and pushed to `origin/main` at
`bc2975c410c2f1eb71da9975d4fd27e8f895cfa9`. Phase 3 continues on fresh branch
`codex/runmux-web-phase3-20261024`; the Phase 2 worktree and branch are retained.
