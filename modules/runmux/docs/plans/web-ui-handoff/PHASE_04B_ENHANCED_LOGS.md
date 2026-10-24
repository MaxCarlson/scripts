# Runmux Web UI — Phase 4B: Enhanced Output Search and Filtering

**Status:** Completed on branch `codex/runmux-web-phase4b-20261024` (Ready for review, do not merge) | **Priority:** P1 | **Backlog:** T08–T09, selected W05–W06

## Objective

Improve the **Output** view with bounded search, match navigation, and conservative severity filtering while keeping ordinary raw/unstructured output accessible. Depend on Phase 2's explicit Output-versus-Terminal representation contract; do not apply line-oriented filtering to the xterm.js screen.

## Implemented Scope

1. **Bounded Buffer Search:**
   - Search is bounded to loaded output buffer (`lastOutput`, capped at `VIEW_LIMIT = 512 KiB`).
   - Scope is explicitly displayed in UI: `(loaded buffer)` or `(loaded tail · earlier output omitted)`.
   - Never claims whole-process totals when truncated.
2. **Search Controls & Navigation:**
   - Query input with clear button (`×`, `Esc`).
   - Match case toggle (`Aa`, `Alt+C`) and Regular expression toggle (`.*`, `Alt+R`).
   - Previous (`▲`, `Shift+Enter`) and Next (`▼`, `Enter`) match navigation buttons with wrap-around.
   - Bounded match count (`10,000` max search matches) with clear status: `No query`, `0 matches ...`, `1 of 5 ...`, `Over 10,000 matches ...`, or `Invalid regex`.
   - Active match automatically scrolls into view (`scrollIntoView({ block: "nearest" })`).
   - Clear follow/scroll interaction: navigating matches away from tail suspends auto-follow; "Jump to latest ↓" or re-checking Follow restores auto-follow.
3. **Safe Match Highlighting & Text Security:**
   - Highlights rendered via DOM text node construction (`<mark class="output-match">` and active `<mark class="output-match active-match">`).
   - 100% immune to XSS injection via malicious log text or search queries.
4. **Conservative Severity Filtering:**
   - Recognizes standard severity levels (`error`, `warn`, `info`, `debug`) without fabricating metadata:
     - JSON formats: `{"level": "error"}` or `{"severity": "INFO"}`.
     - Logfmt: `level=warn` or `severity=error`.
     - Standard bracketed: `[INFO]`, `[ERROR]`, `[DEBUG]`, `[WARN]`.
     - Standard delimited: ` - ERROR - ` or ` - INFO - `.
     - Prefix: `ERROR: `, `WARN: `, `INFO: `, `DEBUG: `.
   - Lines without recognized levels are classified as `"other"`, preserving 100% access to raw/unstructured lines, progress bars, and mixed CLI output.
   - Severity dropdown allows filtering to `all`, `error`, `warn`, `info`, `debug`, or `other`.
5. **Live Streaming Updates:**
   - Dynamic incremental chunk reception via `refreshOutput()` preserves user search term, regex mode, case mode, and severity filter.
   - Recalculates match counts and filtered lines dynamically on stream append.
6. **Scoped Keyboard Shortcuts:**
   - `Ctrl+F` focuses Output search query when the Output pane is active.
   - Strictly prevents intercepting key events when the Terminal pane is active or `#terminal-container` has focus.
   - `Enter` / `Shift+Enter` cycles next/previous matches; `Esc` clears query.

## Validation Evidence

- **Unit tests:** `node tests/dashboard_test.js` passing 21/21 suites.
- **Headless Chrome E2E tests:** `node tests/browser_e2e_test.js` verified on native Windows Google Chrome with Chrome DevTools Protocol (CDP) for 1,000+ line logs, search highlighting, regex, invalid regex, clear, severity filtering, live updates, and XSS immunity.
- **FastAPI / Python tests:** `python -m pytest tests/web_test.py tests/web_adapter_test.py tests/web_cli_test.py -q` passing 29/29 tests.
- **Code quality:** `ruff check src/runmux/web* tests/web*` passed with 0 errors.
