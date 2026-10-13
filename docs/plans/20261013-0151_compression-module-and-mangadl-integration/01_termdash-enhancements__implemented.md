# Stage 1: Termdash Enhancements

> Historical scaffold specification, not accepted completion. REVIEW.md records
> missing width/Unicode behavior; 05_reviewed-plan.md S7 owns corrections.
> Version baseline is0.5.0, existing scaffold0.6.0 (not0.3/0.4 below).

## Goal
Extend the repository's shared `termdash` library (`modules/termdash`) with table rendering and horizontal comparison bar capabilities, meeting the requirement to use and extend `termdash` rather than importing an external formatting framework.

## Scope of Work

1. **Table Renderer (`modules/termdash/table.py`)**:
   - `Table` class and `render_table(headers, rows, alignments=None, style="rule", max_width=None)` function.
   - Computes column widths based on maximum cell content while stripping ANSI escape codes to ensure exact visual alignment.
   - Supports column alignments: `"left"`, `"right"`, `"center"`.
   - Uses Termdash's standard separator styles (`rule` with `─`, `dash` with `-`, `│` column separators, etc.).
   - Honors terminal width limits and gracefully truncates overflowing cells with `…`.
   - Preserves ANSI colors within cell values without disrupting border alignment.

2. **Horizontal Comparison Bar (`modules/termdash/progress.py`)**:
   - `render_horizontal_bar(ratio, width=20, fill_char="█", empty_char="·", color=None, empty_color=None, show_pct=True)` function.
   - Computes filled vs unfilled segment lengths according to `ratio` (`0.0 <= ratio <= 1.0`).
   - Inserts colored text formatting if ANSI colors are enabled.
   - Produces clean output for comparison tables.

3. **Public API & Versioning**:
   - Re-export `Table`, `render_table`, and `render_horizontal_bar` in `modules/termdash/__init__.py`.
   - Bump version in `modules/termdash/pyproject.toml` from `0.3.0` to `0.4.0`.

4. **Testing**:
   - `modules/termdash/tests/table_test.py`:
     - Test header and row alignment with varying lengths.
     - Test ANSI color strings (ensuring escape codes do not alter measured widths).
     - Test column alignment modes (left, right, center).
     - Test truncation on narrow terminal widths.
   - `modules/termdash/tests/horizontal_bar_test.py`:
     - Test 0%, 50%, 100%, and clamped values.
     - Test bar width boundaries and text overlay.
   - Ensure all existing termdash tests continue to pass.
