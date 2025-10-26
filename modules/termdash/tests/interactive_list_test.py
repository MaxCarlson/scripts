from __future__ import annotations

import pytest
from termdash.interactive_list import calculate_size_color, ListState


def test_calculate_size_color_same_size():
    """All items same size should return green."""
    color = calculate_size_color(100, 100, 100)
    assert color == 4  # green


def test_calculate_size_color_smallest():
    """Smallest file should be green."""
    color = calculate_size_color(0, 0, 1000)
    assert color == 4  # green


def test_calculate_size_color_small():
    """Small file (10%) should be green."""
    color = calculate_size_color(100, 0, 1000)
    assert color == 4  # green


def test_calculate_size_color_medium_low():
    """Medium-low file (40%) should be cyan."""
    color = calculate_size_color(400, 0, 1000)
    assert color == 5  # cyan


def test_calculate_size_color_medium():
    """Medium file (60%) should be yellow."""
    color = calculate_size_color(600, 0, 1000)
    assert color == 6  # yellow


def test_calculate_size_color_large():
    """Large file (80%) should be magenta."""
    color = calculate_size_color(800, 0, 1000)
    assert color == 7  # magenta


def test_calculate_size_color_largest():
    """Largest file should be red."""
    color = calculate_size_color(1000, 0, 1000)
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
