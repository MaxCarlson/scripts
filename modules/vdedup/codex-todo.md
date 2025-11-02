# Codex TODO & Log — vdedup Interactive Report UX
_Last updated: 2025-10-29 · Author: Codex (GPT-5)_

Legend:
- `[done]` completed
- `[wip]` in progress
- `[todo]` pending
- `[blocked]` blocked / needs decision

## Completed
- `[done]` Added report data models (`report_models.py`) for keep/loser stats aggregation.
- `[done]` Extended `InteractiveList` with `render_items_to_text` for shared rendering.
- `[done]` Implemented initial interactive report viewer and CLI flag `--view-report`.
- `[done]` Replaced `--print-report` text dump with hierarchical rendering shared with viewer.
- `[done]` Updated tests (`report_print_test.py`) and bumped version to 0.5.0.

## Outstanding Feedback / Issues
- `[todo]` **Compact list formatting**
  - Remove repetitive “KEEP” prefix; use concise role markers (e.g., colored bullet or single-letter tag).
  - Display filenames first; include minimal unique path suffix when needed.
  - Trim redundant path segments for duplicates sharing common directories.
- `[todo]` **Column readability**
  - Introduce header/legend row describing columns (e.g., `dup`, `reclaim`, `keep`).
  - For nested losers, keep indentation but ensure columns remain aligned; consider reprinting header per indent level if necessary.
- `[todo]` **Sorting correctness**
  - Ensure sort keys operate on parent duplicate groups before child rows are injected so UI visibly reorders on `1..5`.
- `[todo]` **Detail/examine view**
  - Add hotkey (e.g., `i`) to open scrollable detail pane for selected group with full stats per file (path, size, duration, resolution, bitrates, deltas).
  - When terminal width is limited, collapse sections and allow expanding individual files within detail view.
- `[todo]` **Global expand/collapse shortcuts**
  - Provide hotkeys (e.g., `E`/`C`) to expand/collapse all groups simultaneously.
- `[todo]` **Print-mode alignment**
  - Update text renderer to mirror compact layout (headers, role markers) and adjust tests accordingly.
- `[todo]` **Automated tests**
  - Add tests covering new formatter output, sorting behavior, and detail view data extraction (non-curses focused).

## Plan of Action
1. Redesign list formatter to emit compact columns + legend and minimal path info.
2. Adjust sort pipeline to order groups before expansion; add focused unit test.
3. Implement detail/examine view with scrolling detail pane and per-file expansion.
4. Add global expand/collapse shortcuts and expose in footer legend.
5. Sync print renderer with new layout; update snapshot assertions.
6. Re-run `pytest` and manually validate viewer on large report for readability.

## Future (post-UX pass)
- Revisit `--analyze-report` progress performance & output clarity.
- Investigate advanced duplicate detection (subset/overlap cases, mixed resolutions) per primary TODO.
- Pursue richer scan-mode progress UI (dashboards/log panes) inspired by `status*.txt`.
