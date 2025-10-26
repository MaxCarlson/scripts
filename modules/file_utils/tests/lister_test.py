
from __future__ import annotations

import pytest
from pathlib import Path
from datetime import datetime

from file_utils import lister

@pytest.fixture
def temp_dir_structure(tmp_path: Path) -> Path:
    """Creates a temporary directory structure for testing."""
    (tmp_path / "file1.txt").touch()
    (tmp_path / "empty_dir").mkdir()
    sub_dir = tmp_path / "sub_dir"
    sub_dir.mkdir()
    (sub_dir / "file2.txt").touch()
    deep_dir = sub_dir / "deep_dir"
    deep_dir.mkdir()
    (deep_dir / "file3.txt").touch()
    return tmp_path

def test_read_entries_recursive_depth_0(temp_dir_structure: Path):
    entries = lister.read_entries_recursive(temp_dir_structure, max_depth=0)
    names = sorted([e.name for e in entries])
    assert names == ["empty_dir", "file1.txt", "sub_dir"]
    for entry in entries:
        assert entry.depth == 0

def test_read_entries_recursive_depth_1(temp_dir_structure: Path):
    entries = lister.read_entries_recursive(temp_dir_structure, max_depth=1)
    paths = sorted([e.path.relative_to(temp_dir_structure).as_posix() for e in entries])
    expected_paths = [
        "empty_dir",
        "file1.txt",
        "sub_dir",
        "sub_dir/deep_dir",
        "sub_dir/file2.txt",
    ]
    assert paths == expected_paths
    
    sub_dir_entry = next(e for e in entries if e.name == "sub_dir")
    assert sub_dir_entry.depth == 0
    
    file2_entry = next(e for e in entries if e.name == "file2.txt")
    assert file2_entry.depth == 1

def test_read_entries_recursive_full_depth(temp_dir_structure: Path):
    # A large max_depth should walk the entire tree
    entries = lister.read_entries_recursive(temp_dir_structure, max_depth=5)
    paths = sorted([e.path.relative_to(temp_dir_structure).as_posix() for e in entries])
    expected_paths = [
        "empty_dir",
        "file1.txt",
        "sub_dir",
        "sub_dir/deep_dir",
        "sub_dir/deep_dir/file3.txt",
        "sub_dir/file2.txt",
    ]
    assert paths == expected_paths
    
    file3_entry = next(e for e in entries if e.name == "file3.txt")
    assert file3_entry.depth == 2

def test_format_entry_line_no_indent():
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/file.txt"),
        name="file.txt",
        is_dir=False,
        size=1024,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
    )
    formatted_line = lister.format_entry_line(entry, "created", 80, show_date=True, show_time=True, scroll_offset=0)
    assert formatted_line.startswith(now.strftime("%Y-%m-%d"))
    assert "  file.txt" in formatted_line
    assert not formatted_line.lstrip().startswith("  ")
    assert "1.0 KB" in formatted_line

def test_format_entry_line_with_indent():
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/sub/file.txt"),
        name="file.txt",
        is_dir=False,
        size=1024,
        created=now,
        modified=now,
        accessed=now,
        depth=2,
    )
    formatted_line = lister.format_entry_line(entry, "created", 80, show_date=True, show_time=True, scroll_offset=0)
    # Check for 2 levels of indentation (4 spaces)
    assert "    file.txt" in formatted_line

def test_format_entry_line_no_date():
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/file.txt"),
        name="file.txt",
        is_dir=False,
        size=1024,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
    )
    formatted_line = lister.format_entry_line(entry, "created", 80, show_date=False, show_time=True, scroll_offset=0)
    assert now.strftime("%Y-%m-%d") not in formatted_line
    assert now.strftime("%H:%M:%S") in formatted_line
    assert "1.0 KB" in formatted_line

def test_format_entry_line_no_time():
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/file.txt"),
        name="file.txt",
        is_dir=False,
        size=1024,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
    )
    formatted_line = lister.format_entry_line(entry, "created", 80, show_date=True, show_time=False, scroll_offset=0)
    assert now.strftime("%Y-%m-%d") in formatted_line
    assert now.strftime("%H:%M:%S") not in formatted_line
    assert "1.0 KB" in formatted_line

def test_format_entry_line_no_date_no_time():
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/file.txt"),
        name="file.txt",
        is_dir=False,
        size=1024,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
    )
    formatted_line = lister.format_entry_line(entry, "created", 80, show_date=False, show_time=False, scroll_offset=0)
    assert now.strftime("%Y-%m-%d") not in formatted_line
    assert now.strftime("%H:%M:%S") not in formatted_line
    assert "file.txt" in formatted_line
    assert "1.0 KB" in formatted_line

def test_format_entry_line_with_scroll():
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/very-long-filename-that-should-scroll-nicely.txt"),
        name="very-long-filename-that-should-scroll-nicely.txt",
        is_dir=False,
        size=1024,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
    )
    # With small width, name gets truncated
    formatted_line_no_scroll = lister.format_entry_line(entry, "created", 50, show_date=True, show_time=True, scroll_offset=0)
    assert "..." in formatted_line_no_scroll

    # With scroll offset, we see different part of the name
    formatted_line_scrolled = lister.format_entry_line(entry, "created", 50, show_date=True, show_time=True, scroll_offset=10)
    # Scrolled version should show different content
    assert formatted_line_scrolled != formatted_line_no_scroll

def test_format_entry_line_folder_collapsed():
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/mydir"),
        name="mydir",
        is_dir=True,
        size=0,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
        expanded=False,
    )
    formatted_line = lister.format_entry_line(entry, "created", 80, show_date=True, show_time=True, scroll_offset=0)
    # Should have collapsed indicator
    assert "▶" in formatted_line
    assert "mydir/" in formatted_line

def test_format_entry_line_folder_expanded():
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/mydir"),
        name="mydir",
        is_dir=True,
        size=0,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
        expanded=True,
    )
    formatted_line = lister.format_entry_line(entry, "created", 80, show_date=True, show_time=True, scroll_offset=0)
    # Should have expanded indicator
    assert "▼" in formatted_line
    assert "mydir/" in formatted_line

def test_lister_manager_toggle_folder(temp_dir_structure: Path):
    entries = lister.read_entries_recursive(temp_dir_structure, max_depth=5)
    manager = lister.ListerManager(entries, max_depth=5)

    # Find a directory entry
    dir_entry = next(e for e in entries if e.is_dir)

    # Initially not expanded
    assert not dir_entry.expanded

    # Toggle to expand
    changed = manager.toggle_folder(dir_entry)
    assert changed
    assert dir_entry.expanded
    assert dir_entry.path in manager.expanded_folders

    # Toggle to collapse
    changed = manager.toggle_folder(dir_entry)
    assert changed
    assert not dir_entry.expanded
    assert dir_entry.path not in manager.expanded_folders

def test_lister_manager_expand_all_at_depth(temp_dir_structure: Path):
    entries = lister.read_entries_recursive(temp_dir_structure, max_depth=5)
    manager = lister.ListerManager(entries, max_depth=5)

    # Expand all at depth 0
    manager.expand_all_at_depth(0)

    # Check that all depth 0 directories are expanded
    for entry in entries:
        if entry.is_dir and entry.depth == 0:
            assert entry.expanded
            assert entry.path in manager.expanded_folders

def test_lister_manager_get_visible_entries(temp_dir_structure: Path):
    entries = lister.read_entries_recursive(temp_dir_structure, max_depth=5)
    manager = lister.ListerManager(entries, max_depth=5)

    # Initially, only depth 0 items are visible (parent_path is None)
    visible = manager.get_visible_entries()
    assert all(e.depth == 0 for e in visible)
    assert len(visible) == 3  # file1.txt, empty_dir, sub_dir

    # Expand a directory
    sub_dir = next(e for e in entries if e.name == "sub_dir")
    manager.toggle_folder(sub_dir)
    visible = manager.get_visible_entries()

    # Now should see sub_dir's direct children (depth 1)
    visible_names = [e.name for e in visible]
    assert "file2.txt" in visible_names  # Direct child of sub_dir
    assert "deep_dir" in visible_names   # Direct child of sub_dir
    # But file3.txt should NOT be visible yet (it's in deep_dir which is not expanded)
    assert "file3.txt" not in visible_names

    # Now expand deep_dir
    deep_dir = next(e for e in entries if e.name == "deep_dir")
    manager.toggle_folder(deep_dir)
    visible = manager.get_visible_entries()

    # Now file3.txt should be visible
    visible_names = [e.name for e in visible]
    assert "file3.txt" in visible_names
