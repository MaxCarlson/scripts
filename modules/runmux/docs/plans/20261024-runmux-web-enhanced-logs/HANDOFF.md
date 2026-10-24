# Runmux Web Enhanced Output Search and Filtering Handoff

**Phase:** RUNMUX-WEB-P4B  
**Branch:** `codex/runmux-web-phase4b-20261024`  
**Base:** `origin/main` at `5ce51607 docs(runmux): reconcile phase 3 integration status`  
**Status:** Completed and Verified (Ready for Review / Push)  

## Overview

Implemented Phase 4B: Enhanced Output Search and Filtering for Runmux Web UI. Provides bounded search over the loaded output buffer (`VIEW_LIMIT = 512 KiB`), match navigation, case sensitivity, safe regular expressions, conservative severity filtering (`all`, `error`, `warn`, `info`, `debug`, `other`), and accurate count/scope labeling (`(loaded buffer)` or `(loaded tail · earlier output omitted)`), while preserving incremental streaming and memory caps.

## Implemented Features

1. **Output Search Bar & Controls:**
   - Query input with clear button (`×`, `Esc`).
   - Match case toggle (`Aa`, `Alt+C`) and Regular expression toggle (`.*`, `Alt+R`).
   - Previous (`▲`, `Shift+Enter`) and Next (`▼`, `Enter`) match navigation buttons with wrap-around.
   - Bounded match count (`10,000` max search matches) with clear status: `No query`, `0 matches ...`, `1 of 5 ...`, `Over 10,000 matches ...`, or `Invalid regex`.
   - Clear and accurate scope indicators: explicitly indicates whether counts are for `(loaded buffer)` or `(loaded tail · earlier output omitted)`.
2. **Safe Match Highlighting & Viewport Navigation:**
   - Renders highlights using safe DOM text nodes (`<mark class="output-match">` and active match `<mark class="output-match active-match">`).
   - 100% immune to XSS injection via user log content or malicious search terms.
   - Navigating matches automatically centers/scrolls the active match into view (`scrollIntoView({ block: "nearest" })`).
   - Suspending follow: navigating away from the tail automatically disables Auto-Follow; clicking "Jump to latest ↓" or re-checking Follow restores auto-scrolling.
3. **Conservative Line Classification & Severity Filtering:**
   - Strictly recognizes standard severity levels (`error`, `warn`, `info`, `debug`) without fabricating metadata:
     - JSON formats: `{"level": "error"}` or `{"severity": "INFO"}`.
     - Logfmt: `level=warn` or `severity=error`.
     - Standard bracketed: `[INFO]`, `[ERROR]`, `[DEBUG]`, `[WARN]`.
     - Standard delimited: ` - ERROR - ` or ` - INFO - `.
     - Prefix: `ERROR: `, `WARN: `, `INFO: `, `DEBUG: `.
   - Lines without recognized levels are classified as `"other"`, preserving 100% access to raw/unstructured lines, progress bars, and mixed CLI output.
   - Severity dropdown allows filtering to `all`, `error`, `warn`, `info`, `debug`, or `other`.
4. **Live Streaming Updates:**
   - Dynamic incremental chunk reception via `refreshOutput()` preserves user search term, regex mode, case mode, and severity filter.
   - Recalculates match counts and filtered lines dynamically on stream append.
5. **Keyboard Shortcuts:**
   - `Ctrl+F` focuses Output search query when the Output pane is active.
   - Strictly prevents intercepting key events when the Terminal pane is active or `#terminal-container` has focus.
   - `Enter` / `Shift+Enter` cycles next/previous matches.
   - `Esc` clears search query and returns to unfiltered text.

## Limitations & Boundaries

- **Search Scope is Bounded to Loaded Buffer:** Output search is performed client-side on the loaded buffer (`VIEW_LIMIT = 512 KiB`). The UI explicitly informs the user if earlier output was omitted by displaying `(loaded tail · earlier output omitted)`. It never falsely claims whole-process totals when output is truncated.
- **Terminal Rendering Untouched:** Does not modify xterm.js or the terminal tab. Line filtering and search are strictly scoped to the plain text Output pane.
- **Backend Lifecycle Isolated:** Did not modify `web.py`, `runner.py`, or lifecycle endpoints.

## Verification Evidence

1. **Automated Unit Tests (`tests/dashboard_test.js`):**
   - 21 test suites passed with 0 failures, covering:
     - `testLogClassificationAndSeverityFiltering()`
     - `testBoundedOutputSearchPlainAndRegex()`
     - `testOutputMatchNavigationAndFollowCoordination()`
     - `testOutputSearchAndFilterAccurateScopeLabeling()`
     - `testOutputLiveStreamingUpdatesSearchAndFilter()`
     - `testOutputTextSecurityAndXssImmunity()`
2. **Real Headless Chrome E2E Test (`tests/browser_e2e_test.js`):**
   - Native Windows Google Chrome launched with `--headless=new` via Chrome DevTools Protocol against a disposable server on `127.0.0.1:8791`.
   - Verified in real Chromium engine:
     - 1,000+ line synthetic log buffer.
     - Plain text search highlighting.
     - Safe regex search (`database:\d+`).
     - Invalid regex handling (`[invalid(`) with `has-error` badge without browser lockup.
     - Clear search button.
     - Severity filtering (`error` vs `other` vs `all`).
     - Dynamic live streaming appends.
     - Complete XSS immunity against `<script>` and `<img> onerror` vectors in user logs.
3. **Python Regression Suite:**
   - `pytest tests/web_test.py tests/web_adapter_test.py tests/web_cli_test.py -q` passed 29/29 tests.
   - `ruff check src/runmux/web* tests/web*` passed clean with 0 warnings.
