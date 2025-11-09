# Codex TODO & Log - vdedup Interactive Report UX
Last updated: 2025-11-02 - Author: Codex (GPT-5)

Legend:
- [done] completed
- [wip] in progress
- [todo] pending
- [blocked] blocked / needs decision

## Completed
- [done] Added report data models (`report_models.py`) for keep/loser stats aggregation.
- [done] Extended `InteractiveList` with `render_items_to_text` for shared rendering.
- [done] Implemented initial interactive report viewer and CLI flag `--view-report`.
- [done] Replaced `--print-report` text dump with hierarchical rendering shared with the viewer.
- [done] Updated tests (`report_print_test.py`) and bumped version to 0.5.0.

## Outstanding Feedback / Issues
- [todo] Compact list formatting
  - Remove repetitive KEEP prefix; rely on concise role markers or color.
  - Display filenames first and append minimal unique path suffix when paths collide.
  - Collapse redundant path segments for duplicates in the same directory tree.
- [todo] Column readability
  - Add a header or legend row describing columns (dup, reclaim, keep, delta).
  - Preserve column alignment for indented losers; consider re-emitting headers when helpful.
- [todo] Sorting correctness
  - Ensure sort keys reorder parent duplicate groups before injecting child rows.
- [todo] Detail or examine view
  - Add a hotkey to open a scrollable detail pane with per-file stats (path, size, duration, resolution, bitrates, deltas).
  - Support expanding or collapsing verbose sections when the terminal is narrow.
- [todo] Global expand and collapse
  - Provide hotkeys to expand or collapse all groups and surface them in the footer legend.
- [todo] Print-mode alignment
  - Mirror the compact layout in `--print-report` output and adjust tests.
- [todo] Automated tests
  - Add coverage for formatter output, sort behavior, and detail view data feed (non-curses focus).

## Session Log 2025-11-02
- [wip] Re-evaluated viewer requirements after user feedback; interactive list readability is the top priority ahead of analysis pipeline.
- [wip] Audited `InteractiveList` implementation: detail mode still uses flat string rendering with limited navigation; hierarchical sorting short-circuits which causes duplicate-count sort failures.
- [todo] Design structured detail payload (`DetailViewData`) with selection-aware expansion, per-entry metadata, and reusable footer legend.
- [todo] Implement compact formatter with header injection and unique path suffix logic.
- [todo] Update `InteractiveList` to draw column headers, handle detail view state, and respect new shortcuts.
- [todo] Wire viewer hotkeys: Enter toggle, Escape collapse, I inspect detail view, E expand all, C collapse all.
- [todo] Refresh print pipeline to use expanded rows from the new formatter and supply the header line.
- [todo] Extend tests covering formatting, sorting, and print changes; rerun `pytest tests` for regression.
- [todo] After viewer polish, revisit failing pipeline tests (`integration_test.py::test_pipeline_exclusion_logic`, `video_dedupe_test.py::test_normalize_patterns_deduplicates_and_normalizes`) in a follow-up pass if not already resolved.

## Plan of Action
1. Redesign the list formatter to emit compact columns with unique path suffixes and provide a reusable header string.
2. Upgrade `InteractiveList` to support the header line, global expand and collapse shortcuts, and a scrollable detail view.
3. Refactor report viewer wiring (formatter, sorter, handlers) to consume the enhanced list features and hotkeys.
4. Synchronize `--print-report` output with the interactive layout and update automated tests.
5. Run targeted pytest suites for `vdedup` and address any regressions surfaced by the new formatting.

## Future (post-UX pass)
- Revisit `--analyze-report` progress performance and output clarity.
- Investigate advanced duplicate detection (subset or overlap cases, mixed resolutions) per primary TODO.
- Pursue richer scan-mode progress UI (dashboards or log panes) inspired by `status*.txt`.
