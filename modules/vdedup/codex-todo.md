# Codex Implementation Plan — vdedup Interactive Report UX

Last updated: 2025-10-29 • Author: Codex (GPT-5)

## Scope
- Ignore `--analyze-report` enhancements for now.
- Deliver a curses-based interactive viewer powered by `modules/termdash/interactive_list.py`.
- Rework `-P/--print-report` to reuse the same rendering logic (fully expanded view) with consistent coloring/styling.
- Extend Termdash list utilities as needed (hierarchy support, expanded output, color hooks).

## Plan of Action

### 1. Data preparation layer
- Build a reusable loader that converts a report JSON into structured objects:
  - `DuplicateGroup` with keep entry, loser entries, aggregate stats (duplicate count, total duplicate size, reclaimable bytes).
  - `DuplicateEntry` for each loser, including computed deltas versus keep (size, duration, resolution, bitrate).
- Cache ffprobe-derived metadata where necessary; gracefully fall back to size-only info if probing unavailable.

### 2. Termdash interactive list enhancements
- Introduce hierarchical item support (parent row with optional children) within `InteractiveList`.
- Add APIs to:
  - Control initial expansion depth (e.g., collapsed by default, optional `expand_all()`).
  - Provide color/style callbacks per row (keep vs loser).
  - Export a static text rendering of the current tree (used by `--print-report`).
- Ensure existing behaviors (sorting, filtering, collapsing via Enter/Esc) continue to work.

### 3. Report viewer CLI integration
- New flag `--view-report PATH [...]` to launch curses UI.
- Adapter to map `DuplicateGroup` objects into Termdash list items:
  - Parent row shows keep path, duplicate count, cumulative reclaimable size.
  - Child rows show loser paths with indented formatting and key metrics.
- Provide sensible default sort keys: `size_saved`, `duplicate_count`, `method`, `path`.
- Handle missing curses dependency with helpful message (reuse `ensure_curses_available()`).

### 4. Enhanced print output (`-P/--print-report`)
- Replace current summary-only output with the static renderer from step 2:
  - Expand all groups to a specified depth (default infinite for non-interactive printout).
  - Apply the same labeling/color choices (fall back to plain text when ANSI disabled).
- Keep verbosity flag semantics (v=0 totals, v>=1 full hierarchy).

### 5. Testing & validation
- Add/extend unit tests covering:
  - Report loader data structures.
  - Termdash hierarchy handling (non-curses unit tests around data transforms/static rendering).
  - CLI print output (snapshot-style asserts with ANSI stripped).
- Manual verification: run `--view-report` against sample report, ensure navigation/sorting behaves.

### 6. Future follow-ups (out of current scope)
- Revisit `--analyze-report` for performance/UI upgrades.
- Investigate advanced duplicate detection (subset/overlap cases, multi-resolution streams).
- Align progress UI with richer live dashboards per `todo.txt`.

## Immediate next steps
1. Implement data preparation layer (`report_loader.py` or similar) with tests.
2. Extend `InteractiveList` for hierarchy + static rendering.
3. Wire new viewer flag and revamped `--print-report` to the shared renderer.
