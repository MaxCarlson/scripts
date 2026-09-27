from __future__ import annotations

from termdash.interactive_list import calculate_size_color, ListState, InteractiveList


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
    footer_lines = [
        "↑↓/jk/PgUp/Dn │ f:filter x:exclude │ ↵:expand ESC:collapse ^Q:quit",
        "Sort c/m/a/n/s | e:depth | F:dirs t:time | y:copy r:one A:vis S:all | ←→",
    ]

    for line in footer_lines:
        # Each line should fit in 80 columns
        assert len(line) <= 80, f"Footer line too long ({len(line)} chars): {line}"


def test_invoke_handler_supports_two_or_three_args():
    calls = []

    def handler_two(key, item):
        calls.append(("two", key, item))
        return True, False

    def handler_three(key, item, state):
        calls.append(("three", key, item, state.header))
        return True, True

    list_view = InteractiveList(
        items=["a"],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: True,
        key_handler=handler_three,
        custom_action_handler=handler_two,
    )

    handled, refresh = list_view._invoke_handler(handler_two, 1, "a")
    assert handled is True and refresh is False
    handled3, refresh3 = list_view._invoke_handler(handler_three, 2, "b")
    assert handled3 is True and refresh3 is True
    assert calls[0] == ("two", 1, "a")
    assert calls[1][0:3] == ("three", 2, "b")


def test_multiselect_enforces_limit():
    captured = []

    def on_selection_change(items):
        captured.append([*items])

    list_view = InteractiveList(
        items=["a", "b", "c"],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: True,
        multi_select=True,
        multi_select_limit=2,
        item_key_func=lambda item: item,
        selection_change_handler=on_selection_change,
    )
    list_view._update_visible_items(reset_selection=True)
    list_view._toggle_selection("a")
    list_view._toggle_selection("b")
    list_view._toggle_selection("c")  # should drop "a"
    selected = list_view.get_selected_items()
    assert selected == ["b", "c"]
    assert captured[-1] == ["b", "c"]


def test_apply_selection_replaces_choices():
    list_view = InteractiveList(
        items=["x", "y"],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: True,
        multi_select=True,
        item_key_func=lambda item: item,
    )
    list_view._update_visible_items(reset_selection=True)
    list_view.apply_selection(["x"], notify=False)
    assert list_view.get_selected_items() == ["x"]
    list_view.apply_selection(["y"], notify=False)
    assert list_view.get_selected_items() == ["y"]


def test_checkbox_prefix():
    list_view = InteractiveList(
        items=["item1", "item2"],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: True,
        multi_select=True,
        render_checkbox=True,
        item_key_func=lambda item: item,
    )
    list_view._update_visible_items(reset_selection=True)
    assert list_view._render_checkbox_prefix("item1", False) == "[ ] "
    assert list_view._render_checkbox_prefix("item1", True) == "[x] "

    # When checkbox rendering is disabled
    list_view.render_checkbox = False
    assert list_view._render_checkbox_prefix("item1", True) == ""


def test_range_select():
    list_view = InteractiveList(
        items=["a", "b", "c", "d", "e"],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: True,
        initial_order="asc",
        multi_select=True,
        item_key_func=lambda item: item,
    )
    list_view._update_visible_items(reset_selection=True)

    # Position on index 1 ("b") and start range select
    list_view.state.selected_index = 1
    list_view._toggle_range_select()
    assert list_view.state.in_range_select is True
    assert list_view.state.range_select_anchor == 1
    assert list_view.get_selected_items() == ["b"]

    # Move cursor down 2 places (to index 3: "d")
    list_view._move_selection(2)
    assert list_view.state.selected_index == 3
    assert list_view.get_selected_items() == ["b", "c", "d"]

    # Toggle range select off
    list_view._toggle_range_select()
    assert list_view.state.in_range_select is False
    assert list_view.state.range_select_anchor is None
    # Selection is retained
    assert list_view.get_selected_items() == ["b", "c", "d"]


def test_delete_and_multi_level_undo():
    deleted_log = []
    restored_log = []

    def on_delete(items):
        deleted_log.append(list(items))
        return "payload-" + ",".join(items)

    def on_undo(items, payload):
        restored_log.append((list(items), payload))

    list_view = InteractiveList(
        items=["a", "b", "c", "d"],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: True,
        initial_order="asc",
        multi_select=True,
        enable_delete=True,
        delete_handler=on_delete,
        undo_handler=on_undo,
        item_key_func=lambda item: item,
    )
    list_view._update_visible_items(reset_selection=True)

    # Delete single item "b"
    list_view.state.selected_index = 1
    list_view._trigger_delete()
    assert list_view.state.confirm_delete is True
    assert list_view.state.pending_delete_items == ["b"]

    list_view._execute_delete(list_view.state.pending_delete_items)
    assert [x for x in list_view.state.items] == ["a", "c", "d"]
    assert len(list_view.state.undo_stack) == 1
    assert deleted_log == [["b"]]

    # Now multi-select "c" and "d" and delete them together
    list_view._set_item_selected("c", True)
    list_view._set_item_selected("d", True)
    list_view._trigger_delete()
    assert list_view.state.pending_delete_items == ["c", "d"]

    list_view._execute_delete(list_view.state.pending_delete_items)
    assert [x for x in list_view.state.items] == ["a"]
    assert len(list_view.state.undo_stack) == 2

    # Undo 1st time: restores both "c" and "d" in ONE step
    list_view._undo()
    assert sorted(list_view.state.items) == ["a", "c", "d"]
    assert len(list_view.state.undo_stack) == 1
    assert restored_log[-1] == (["c", "d"], "payload-c,d")

    # Undo 2nd time: restores "b"
    list_view._undo()
    assert sorted(list_view.state.items) == ["a", "b", "c", "d"]
    assert len(list_view.state.undo_stack) == 0
    assert restored_log[-1] == (["b"], "payload-b")

    # Further undo does nothing
    list_view._undo()
    assert len(list_view.state.undo_stack) == 0


def test_delete_all_and_undo():
    list_view = InteractiveList(
        items=["x", "y", "z"],
        sorters={"name": lambda x: x},
        formatter=lambda item, field, width, date, time, scroll: str(item),
        filter_func=lambda item, pattern: True,
        initial_order="asc",
        enable_delete=True,
        require_typed_delete_for_all=True,
        item_key_func=lambda item: item,
    )
    list_view._update_visible_items(reset_selection=True)

    list_view._trigger_delete_all()
    assert list_view.state.confirm_delete_all is True
    assert list_view.state.pending_delete_items == ["x", "y", "z"]

    # Execute delete all
    list_view._execute_delete(list_view.state.pending_delete_items)
    assert list_view.state.items == []
    assert list_view.state.visible == []

    # Undo restores all items
    list_view._undo()
    assert list_view.state.items == ["x", "y", "z"]


def test_items_summary():
    class DummyItem:
        def __init__(self, name, size, files):
            self.name = name
            self.size = size
            self.files = files

    items = [
        DummyItem("item1", 1024 * 1024 * 50, 100),
        DummyItem("item2", 1024 * 1024 * 150, 400),
    ]

    list_view = InteractiveList(
        items=items,
        sorters={"name": lambda x: x.name},
        formatter=lambda item, field, width, date, time, scroll: item.name,
        filter_func=lambda item, pattern: True,
        size_extractor=lambda item: item.size,
        files_extractor=lambda item: item.files,
        enable_delete=True,
    )
    summary = list_view._items_summary(items)
    assert "500 files" in summary
    assert "200.00 MiB" in summary


def test_bidirectional_range_selection():
    items = ["a", "b", "c", "d", "e"]
    list_view = InteractiveList(
        items=items,
        sorters={"name": lambda x: x},
        formatter=lambda item, *_: item,
        initial_order="asc",
        multi_select=True,
        item_key_func=lambda item: item,
    )
    list_view._update_visible_items(reset_selection=True)

    # Start range select from index 0 ('a', initially unselected)
    list_view.state.selected_index = 0
    list_view._toggle_range_select()
    assert list_view.state.in_range_select is True
    assert list_view.state.range_select_target is True
    assert list_view.get_selected_items() == ["a"]

    # Move cursor down to index 2 ('c')
    list_view._move_selection(2)
    assert list_view.get_selected_items() == ["a", "b", "c"]

    # Reverse direction up to index 1 ('b') -> 'c' must be restored to unselected
    list_view._move_selection(-1)
    assert list_view.get_selected_items() == ["a", "b"]

    # Expand down to index 4 ('e')
    list_view._move_selection(3)
    assert list_view.get_selected_items() == ["a", "b", "c", "d", "e"]

    # End range selection
    list_view._toggle_range_select()
    assert list_view.state.in_range_select is False
    assert list_view.get_selected_items() == ["a", "b", "c", "d", "e"]

    # Now test range unselect starting on an already-selected item
    list_view.state.selected_index = 2  # 'c'
    list_view._toggle_range_select()
    assert list_view.state.in_range_select is True
    assert list_view.state.range_select_target is False  # Target is unselect!
    assert list_view.get_selected_items() == ["a", "b", "d", "e"]

    # Move down to index 4 ('e') -> 'c', 'd', 'e' are unselected
    list_view._move_selection(2)
    assert set(list_view.get_selected_items()) == {"a", "b"}

    # Reverse direction up to index 3 ('d') -> 'e' is restored to selected!
    list_view._move_selection(-1)
    assert set(list_view.get_selected_items()) == {"a", "b", "e"}

    list_view._toggle_range_select()
    assert list_view.state.in_range_select is False


def test_toggle_select_all():
    items = ["a", "b", "c"]
    list_view = InteractiveList(
        items=items,
        sorters={"name": lambda x: x},
        formatter=lambda item, *_: item,
        initial_order="asc",
        multi_select=True,
        item_key_func=lambda item: item,
    )
    list_view._update_visible_items(reset_selection=True)

    # Initial state: none selected -> toggle selects all
    list_view.toggle_select_all()
    assert set(list_view.get_selected_items()) == {"a", "b", "c"}

    # When all selected -> toggle unselects all
    list_view.toggle_select_all()
    assert list_view.get_selected_items() == []

    # When partially selected -> toggle selects all
    list_view._toggle_selection("b")
    assert list_view.get_selected_items() == ["b"]
    list_view.toggle_select_all()
    assert set(list_view.get_selected_items()) == {"a", "b", "c"}


def test_tree_tri_state_selection_and_rendering():
    class Node:
        def __init__(self, path: str, parent_path: str | None = None):
            self.path = path
            self.parent_path = parent_path
            self.name = path.split("/")[-1]

    root = Node("/root")
    c1 = Node("/root/c1", parent_path="/root")
    c2 = Node("/root/c2", parent_path="/root")

    list_view = InteractiveList(
        items=[root, c1, c2],
        sorters={"name": lambda x: x.name},
        formatter=lambda item, *_: item.name,
        initial_order="asc",
        multi_select=True,
        item_key_func=lambda item: item.path,
    )
    list_view._update_visible_items(reset_selection=True)

    # Checkbox prefixes are all fixed 4 chars at column 0
    assert list_view._render_checkbox_prefix(root, False) == "[ ] "
    assert list_view._render_checkbox_prefix(root, "partial") == "[-] "
    assert list_view._render_checkbox_prefix(root, True) == "[x] "
    assert list_view._render_checkbox_prefix(c1, False) == "[ ] "
    assert list_view._render_checkbox_prefix(c1, True) == "[x] "

    # Initially none selected
    assert list_view._item_selection_state(root) is False

    # Select child c1 -> c1 is True, root becomes 'partial' ([-])
    list_view._toggle_selection(c1)
    assert list_view._item_selection_state(c1) is True
    assert list_view._item_selection_state(c2) is False
    assert list_view._item_selection_state(root) == "partial"
    assert list_view.get_selected_items() == [c1]

    # Toggling a 'partial' parent unselects all its descendants
    list_view._toggle_selection(root)
    assert list_view._item_selection_state(root) is False
    assert list_view._item_selection_state(c1) is False
    assert list_view._item_selection_state(c2) is False
    assert list_view.get_selected_items() == []

    # Toggling an unselected parent selects parent and all descendants ([x])
    list_view._toggle_selection(root)
    assert list_view._item_selection_state(root) is True
    assert list_view._item_selection_state(c1) is True
    assert list_view._item_selection_state(c2) is True
    assert set(list_view.get_selected_items()) == {root, c1, c2}

    # Unselect c2 -> root becomes 'partial'
    list_view._toggle_selection(c2)
    assert list_view._item_selection_state(c2) is False
    assert list_view._item_selection_state(c1) is True
    assert list_view._item_selection_state(root) == "partial"
    assert set(list_view.get_selected_items()) == {c1}

    # Toggling a 'partial' parent unselects all again
    list_view._toggle_selection(root)
    assert list_view._item_selection_state(root) is False
    assert list_view._item_selection_state(c1) is False
    assert list_view._item_selection_state(c2) is False
    assert list_view.get_selected_items() == []


def test_range_select_esc_cancellation():
    items = [f"item_{i}" for i in range(5)]
    list_view = InteractiveList(
        items=items,
        sorters={"name": lambda x: x},
        formatter=lambda item, *_: item,
        initial_order="asc",
        multi_select=True,
        item_key_func=lambda item: item,
    )
    list_view._update_visible_items(reset_selection=True)

    # Case 1: Press 'v' once without moving cursor, then cancel with Esc
    assert list_view.state.selected_index == 0
    assert list_view.state.multi_selected_keys == {}

    # Press 'v' once
    list_view._toggle_range_select()
    assert list_view.state.in_range_select is True
    assert "item_0" in list_view.state.multi_selected_keys

    # Press Esc (triggers _cancel_range_select)
    list_view._cancel_range_select()
    assert list_view.state.in_range_select is False
    assert list_view.state.multi_selected_keys == {}
    assert "Range selection cancelled." in list_view.state.status_message

    # Case 2: Some items initially selected, start range select and expand, then cancel with Esc
    list_view._set_item_selected("item_4", True)
    assert set(list_view.state.multi_selected_keys.keys()) == {"item_4"}

    list_view.state.selected_index = 1
    # Press 'v' on item_1
    list_view._toggle_range_select()
    assert list_view.state.in_range_select is True
    assert "item_1" in list_view.state.multi_selected_keys
    assert "item_4" in list_view.state.multi_selected_keys

    # Move cursor to item_3
    list_view._move_selection(2)  # from 1 to 3
    assert list_view.state.selected_index == 3
    assert set(list_view.state.multi_selected_keys.keys()) == {"item_1", "item_2", "item_3", "item_4"}

    # Press Esc to cancel
    list_view._cancel_range_select()
    assert list_view.state.in_range_select is False
    # Exactly item_4 should remain selected (restored to initial state before 'v')
    assert set(list_view.state.multi_selected_keys.keys()) == {"item_4"}
    assert "Range selection cancelled." in list_view.state.status_message


