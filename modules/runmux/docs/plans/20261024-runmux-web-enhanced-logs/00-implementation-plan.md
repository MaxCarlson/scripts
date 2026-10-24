# Runmux Web Enhanced Output Search and Filtering Implementation Plan

**Phase:** RUNMUX-WEB-P4B  
**Branch:** `codex/runmux-web-phase4b-20261024`  
**Base:** `origin/main` at `5ce51607 docs(runmux): reconcile phase 3 integration status`  
**Spec:** [`web-ui-handoff/PHASE_04B_ENHANCED_LOGS.md`](../web-ui-handoff/PHASE_04B_ENHANCED_LOGS.md)  

## Goal and architecture

Enhance the Runmux browser **Output** view with bounded text and regex search, highlighted match navigation, and conservative severity filtering while keeping ordinary unstructured log lines fully accessible.

Search and filtering operate client-side over the loaded, normalized output buffer (`lastOutput`, capped at `VIEW_LIMIT = 512 KiB`). All match counts and line counts are explicitly scoped to the loaded buffer (or loaded tail if truncated), never implying whole-process totals when history is omitted. Match highlighting uses safe DOM nodes to guarantee complete immunity from HTML injection or XSS.

Do not modify xterm.js terminal rendering, supervisor attachments, telemetry, or backend lifecycle code (`web.py`, `runner.py`).

## Verified current contracts

- Output chunks are retrieved from `/api/runs/{run_id}/output` as bounded text chunks (up to 64 KiB default, max 512 KiB).
- `read_output_chunk` in `web_adapter.py` strips terminal controls and provides UTF-8 decoded text.
- `dashboard.js` accumulates text into `lastOutput`, normalizing `\r` and capping at `VIEW_LIMIT = 512 KiB`.
- `#output-text` displays `lastOutput` inside a `<pre>` element.
- Auto-follow scrolls to bottom when `#follow-output` is checked; manual scroll away disables `#follow-output`. "Jump to latest" re-enables it and scrolls to bottom.
- When truncated, `outputNote` states `"Latest 64 KiB shown · earlier output omitted"`.

## Decisions and boundaries

1. **Client-side bounded search & filtering:**
   - Search operates over the loaded buffer lines.
   - Match count and status clearly indicate scope: e.g., `1 of 8 (loaded buffer)` or `1 of 8 (loaded tail · earlier output omitted)`.
2. **Safe regex handling:**
   - Case-sensitivity (`Aa`) and regex (`.*`) toggles.
   - Invalid regex syntax displays an inline error without crashing or throwing unhandled errors.
   - Infinite loop and ReDoS protections: query length limit (256 chars), empty-match index advance, max match cap (10,000).
3. **Conservative severity classification:**
   - Classify lines into `error`, `warn`, `info`, `debug`, or `other` (unstructured).
   - Only classify where standard patterns match (e.g., `[ERROR]`, `level=error`, `ERROR:`, `{"level":"error"}`).
   - Retain access to unrecognized lines via `All levels` and explicit `Unstructured / Other`.
   - Never fabricate log levels.
4. **Match navigation & highlighting:**
   - Highlight matches with `<mark class="output-match">` and active match with `.active-match`.
   - Navigation via Prev/Next buttons and Enter/Shift+Enter.
   - Navigating to matches scrolls the target into view and suspends auto-follow.
   - Clear button (and Escape) clears query.
5. **Security & XSS prevention:**
   - Construct highlight nodes strictly using `document.createTextNode` and `document.createElement`.
   - Never assign untrusted output into `innerHTML`.
6. **Keyboard shortcuts:**
   - Bounded, browser-safe shortcuts: Enter / Shift+Enter in search input; Esc to clear; Ctrl+F / `/` to focus search when Output tab is active.
   - Never intercept keys when terminal view is active or terminal container has focus.

## File changes

- `modules/runmux/src/runmux/web_static/index.html`: Output search bar and filter controls markup.
- `modules/runmux/src/runmux/web_static/assets/dashboard.css`: Styling for search bar, toggles, badges, match highlights.
- `modules/runmux/src/runmux/web_static/assets/dashboard.js`: Search, safe regex, highlighting, severity filter, navigation, scope labels.
- `modules/runmux/tests/dashboard_test.js`: Comprehensive automated tests for Phase 4B features.
- `modules/runmux/docs/...`: Plans, handoffs, status, roadmap updates.
