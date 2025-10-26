from __future__ import annotations

import pytest
from termdash.interactive_list import calculate_size_color, ListState


def test_calculate_size_color_same_size():
    """All items same size should return green."""
    color = calculate_size_color(100, 100, 100)
    assert color == 4  # green


def test_calculate_size_color_smallest():
    """Smallest file should be green."""
    color = calculate_size_color(0, 0, 1000000)
    assert color == 4  # green


def test_calculate_size_color_small():
    """Small file should be green (log scale)."""
    # Using powers of 10 to test logarithmic distribution
    # Size 10 out of 1,000,000 should be in the lower range
    color = calculate_size_color(10, 1, 1000000)
    assert color == 4  # green


def test_calculate_size_color_medium_low():
    """Medium-low file should be cyan (log scale)."""
    # Size 100 out of 1,000,000: log ratio ~0.34, should be cyan (0.20-0.40)
    color = calculate_size_color(100, 1, 1000000)
    assert color == 5  # cyan


def test_calculate_size_color_medium():
    """Medium file should be yellow (log scale)."""
    # Size 1,000 out of 1,000,000: log ratio ~0.47, should be yellow (0.40-0.60)
    color = calculate_size_color(1000, 1, 1000000)
    assert color == 6  # yellow


def test_calculate_size_color_large():
    """Large file should be magenta (log scale)."""
    # Size 10,000 out of 1,000,000: log ratio ~0.65, should be magenta (0.60-0.80)
    color = calculate_size_color(10000, 1, 1000000)
    assert color == 7  # magenta


def test_calculate_size_color_largest():
    """Largest file should be red."""
    color = calculate_size_color(1000000, 1, 1000000)
    assert color == 8  # red


def test_list_state_defaults():
    """Test ListState default values."""
    state = ListState(
        items=[],
        sorters={},
        filter_func=lambda item, p: True,
    )
    assert state.header == "Interactive List"
    assert state.filter_pattern == ""
    assert state.selected_index == 0
    assert state.top_index == 0
    assert state.viewport_height == 1
    assert state.editing_filter == False
    assert state.detail_view == False
    assert state.scroll_offset == 0
    assert state.show_date == True
    assert state.show_time == True
    assert state.dirs_first == True
    assert state.calculating_sizes == False
    assert state.calc_progress == (0, 0)
    assert state.calc_cancel == False


def test_list_state_toggle_display_options():
    """Test toggling display options."""
    state = ListState(
        items=[],
        sorters={},
        filter_func=lambda item, p: True,
    )

    # Toggle date
    state.show_date = not state.show_date
    assert state.show_date == False

    # Toggle time
    state.show_time = not state.show_time
    assert state.show_time == False

    # Toggle back
    state.show_date = not state.show_date
    state.show_time = not state.show_time
    assert state.show_date == True
    assert state.show_time == True

def test_exclusion_filter_defaults():
    """Test exclusion filter default values in ListState."""
    state = ListState(
        items=[],
        sorters={},
        filter_func=lambda item, p: True,
    )
    assert state.exclusion_pattern == ""
    assert state.editing_exclusion == False
    assert state.exclusion_edit_buffer == ""

def test_matches_pattern_single():
    """Test _matches_pattern with single pattern."""
    from termdash.interactive_list import InteractiveList
    from fnmatch import fnmatch

    list_view = InteractiveList(
        items=[],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: fnmatch(str(item), pattern),
    )

    # Single pattern should match
    assert list_view._matches_pattern("test.py", "*.py") == True
    assert list_view._matches_pattern("test.txt", "*.py") == False

def test_matches_pattern_multi():
    """Test _matches_pattern with multiple patterns using | separator."""
    from termdash.interactive_list import InteractiveList
    from fnmatch import fnmatch

    list_view = InteractiveList(
        items=[],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: fnmatch(str(item), pattern),
    )

    # Multi-pattern with | should match if any pattern matches
    assert list_view._matches_pattern("test.py", "*.py|*.txt") == True
    assert list_view._matches_pattern("test.txt", "*.py|*.txt") == True
    assert list_view._matches_pattern("test.log", "*.py|*.txt") == False

def test_footer_fits_80_columns():
    """Test that footer lines fit in 80-column terminal."""
    # These are the actual footer lines from lister.py
    footer_lines = [
        "↑↓/jk/PgUp/Dn │ f:filter x:exclude │ ↵:expand ESC:collapse ^Q:quit",
        "Sort c/m/a/n/s │ e:all o:open F:dirs │ d:date t:time │ y:copy S:calc │ ←→",
    ]

    for line in footer_lines:
        # Each line should fit in 80 columns
        assert len(line) <= 80, f"Footer line too long ({len(line)} chars): {line}"
