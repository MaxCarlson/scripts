# Runmux Web UI — Phase 4B: Enhanced Output Search and Filtering

**Status:** Completed with bounded-performance protections on branch `codex/runmux-web-phase4b-20261024` | **Priority:** P1 | **Backlog:** T08–T09, selected W05–W06

## Objective

Improve the **Output** view with bounded search, match navigation, and conservative severity filtering while keeping ordinary raw/unstructured output accessible. Depend on Phase 2's explicit Output-versus-Terminal representation contract; do not apply line-oriented filtering to the xterm.js screen.

## Implemented Scope & Performance Boundaries

1. **Safe Bounded Buffer Search:**
   - Search is bounded to loaded output buffer (`lastOutput`, capped at `VIEW_LIMIT = 512 KiB`).
   - Query input with clear button (`×`, `Esc`).
   - Match case toggle (`Aa`, `Alt+C`).
   - Un-sandboxed regex mode disabled to eliminate catastrophic backtracking (ReDoS); all searches run as linear-time $O(N)$ literal substring matches with meta-character escaping.
   - Previous (`▲`, `Shift+Enter`) and Next (`▼`, `Enter`) match navigation buttons with wrap-around.
   - Bounded match count (`10,000` max search matches) reporting exact states: `No query`, `0 matches ...`, `N of M ...`, or `Over 10,000 matches ...`.
   - Explicit scope labeling: clearly reports `(loaded buffer)` or `(loaded tail · earlier output omitted)`.
2. **Pathological Buffer Protection & Bounded DOM Rendering:**
   - For pathological buffers with very large line counts (e.g. 5,000 to 50,000 short lines), DOM element creation is strictly bounded to `MAX_RENDER_LINES = 2000` via a sliding window centered around the active match.
   - Highlighting density is bounded to `MAX_RENDER_MATCHES = 500` marks, ensuring active match is always rendered and highlighted while preventing DOM bloat.
   - Search scope and count labels explicitly declare when a partial window is displayed:
     - Count: `1 of 5,000 (loaded buffer · lines 1–2,000 displayed)`
     - Scope note: `Loaded buffer: 5,000 lines · 183 KiB (displaying lines 1–2,000)`
   - Filtered lines and total line count are cached to eliminate redundant re-splitting and re-classification during match navigation.
3. **Safe Match Highlighting & Follow Coordination:**
   - Highlights rendered via DOM text node construction (`<mark class="output-match">` and active `<mark class="output-match active-match">`). 100% immune to XSS injection.
   - Navigating matches automatically scrolls the active match into view (`scrollIntoView({ block: "nearest" })`).
   - Clear follow/scroll interaction: navigating matches away from tail suspends auto-follow; "Jump to latest ↓" or re-checking Follow restores auto-follow.
4. **Conservative Severity Filtering:**
   - Recognizes standard severity levels (`error`, `warn`, `info`, `debug`) without fabricating metadata (JSON, logfmt, bracketed, delimited, prefix).
   - Lines without recognized levels are classified as `"other"`, preserving 100% access to raw/unstructured lines, progress bars, and mixed CLI output.
   - Severity dropdown allows filtering to `all`, `error`, `warn`, `info`, `debug`, or `other`.
5. **Live Streaming Updates:**
   - Dynamic incremental chunk reception via `refreshOutput()` preserves user search term, case mode, and severity filter.
   - Recalculates match counts and filtered lines dynamically on stream append.
6. **Scoped Keyboard Shortcuts:**
   - `Ctrl+F` focuses Output search query when the Output pane is active.
   - Strictly prevents intercepting key events when the Terminal pane is active or `#terminal-container` has focus.
   - `Enter` / `Shift+Enter` cycles next/previous matches; `Esc` clears query.

## Validation Evidence

- **Unit tests:** `node tests/dashboard_test.js` passing 22/22 suites, including ReDoS protection (<50ms execution) and DOM node bounding under 5,000-line synthetic buffers.
- **Headless Chrome E2E tests:** `node tests/browser_e2e_test.js` verified on native Windows Google Chrome with Chrome DevTools Protocol (CDP) for 5,000+ line logs, search highlighting, literal search with brackets, ReDoS pattern input with zero UI freeze, clear, severity filtering, live updates, DOM element bounding to 2,000 nodes, and XSS immunity.
- **FastAPI / Python tests:** `python -m pytest tests/web_test.py tests/web_adapter_test.py tests/web_cli_test.py -q` passing 29/29 tests.
- **Code quality:** `ruff check src/runmux/web* tests/web*` passed clean with 0 warnings.
