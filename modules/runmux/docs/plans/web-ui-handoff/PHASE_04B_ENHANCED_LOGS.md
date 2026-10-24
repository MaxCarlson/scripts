# Runmux Web UI — Phase 4B: Enhanced Output Search and Filtering

**Status:** Future separately assignable feature | **Priority:** P1 | **Backlog:** T08–T09, selected W05–W06

## Objective

Improve the **Output** view with bounded search, match navigation, and conservative severity filtering while keeping ordinary raw/unstructured output accessible. Depend on Phase 2's explicit Output-versus-Terminal representation contract; do not apply line-oriented filtering to the xterm.js screen.

## In-scope implementation when assigned

1. Inspect current incremental output, retained log retrieval, encoding, truncation and browser-memory caps. Decide and document whether search is limited to loaded lines or uses a bounded server-side query; show the scope in the UI.
2. Add query, next/previous match, highlights, optional case/regex (if safely bounded), and a clear follow/scroll interaction. Malformed regex must show an error, not lock up the browser.
3. Add **recognizable** DEBUG/INFO/WARN/ERROR filters if reliable from the actual source. Keep All/Other access to unrecognized lines, progress output and mixed formats.
4. If showing counts, label their exact scope (visible buffer, filtered loaded data or explicitly queried complete retained range). Never claim whole-process totals from a truncated tail.
5. Browser-safe focused keyboard shortcuts are optional; never intercept keys meant for terminal input or dangerous browser shortcuts.

## Validation and acceptance

Test synthetic plain, mixed, ANSI-decorated and unstructured logs; invalid regex; truncated history; rolling output while scrolled away; large-output bounds; and no XSS through user text. Preserve the existing simple Output view as a fallback. No fabricated levels, hidden lines, unbounded scanning, split streams, process mutations, or terminal rendering changes.

Deliver code, focused tests, documentation, pushed branch and evidence of exact supported search/count scope; **do not merge**.
