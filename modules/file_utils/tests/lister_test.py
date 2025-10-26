
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

def test_calculate_folder_size(temp_dir_structure: Path):
    """Test folder size calculation."""
    # Write some data to files
    (temp_dir_structure / "file1.txt").write_text("a" * 100)
    sub_dir = temp_dir_structure / "sub_dir"
    (sub_dir / "file2.txt").write_text("b" * 200)
    deep_dir = sub_dir / "deep_dir"
    (deep_dir / "file3.txt").write_text("c" * 300)

    # Calculate size of sub_dir (should include deep_dir contents)
    total_size, item_count = lister.calculate_folder_size(sub_dir)

    # Should count file2.txt (200) + file3.txt (300) = 500 bytes
    # Item count: file2.txt, deep_dir, file3.txt = 3
    assert total_size == 500
    assert item_count == 3

def test_entry_calculated_size():
    """Test Entry calculated size methods."""
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/mydir"),
        name="mydir",
        is_dir=True,
        size=4096,  # stat size
        created=now,
        modified=now,
        accessed=now,
        depth=0,
    )

    # Initially no calculated size
    assert not entry.has_calculated_size()
    assert entry.get_display_size() == 4096

    # Set calculated size
    entry.calculated_size = 1024000
    entry.item_count = 42

    assert entry.has_calculated_size()
    assert entry.get_display_size() == 1024000

def test_format_entry_line_folder_with_calculated_size():
    """Test folder formatting with calculated size."""
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/mydir"),
        name="mydir",
        is_dir=True,
        size=4096,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
        expanded=True,
        calculated_size=1024000,
        item_count=42,
    )
    formatted_line = lister.format_entry_line(entry, "created", 100, show_date=True, show_time=True, scroll_offset=0)

    # Should show calculated size with item count (abbreviated)
    assert "1000.0 KB" in formatted_line or "1.0 MB" in formatted_line
    assert "(42)" in formatted_line  # Count < 1000 shows as just number in parens

def test_format_entry_line_folder_calculating():
    """Test folder formatting while calculating size."""
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/mydir"),
        name="mydir",
        is_dir=True,
        size=4096,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
        expanded=False,
        size_calculating=True,
    )
    formatted_line = lister.format_entry_line(entry, "created", 100, show_date=True, show_time=True, scroll_offset=0)

    # Should show spinner indicator
    assert "[...]" in formatted_line

def test_format_entry_line_folder_not_calculated():
    """Test folder formatting without calculated size."""
    now = datetime.now()
    entry = lister.Entry(
        path=Path("/fake/mydir"),
        name="mydir",
        is_dir=True,
        size=4096,
        created=now,
        modified=now,
        accessed=now,
        depth=0,
        expanded=False,
    )
    formatted_line = lister.format_entry_line(entry, "created", 100, show_date=True, show_time=True, scroll_offset=0)

    # Should show blank size for uncalculated folders
    # The size part should be empty/blank, but other parts should be present
    assert "mydir/" in formatted_line

def test_folders_first_sorting_by_name():
    """Test folders-first with name sorting (ascending)."""
    now = datetime.now()
    entries = [
        lister.Entry(Path("/a/file.txt"), "file.txt", False, 100, now, now, now, 0),
        lister.Entry(Path("/a/zdir"), "zdir", True, 0, now, now, now, 0),
        lister.Entry(Path("/a/adir"), "adir", True, 0, now, now, now, 0),
        lister.Entry(Path("/a/bfile.txt"), "bfile.txt", False, 200, now, now, now, 0),
    ]
    manager = lister.ListerManager(entries, max_depth=0)

    # Get visible with dirs_first=True, ascending
    visible = manager.get_visible_entries(lambda e: e.name.lower(), descending=False, dirs_first=True)

    # Should see: adir, zdir, bfile.txt, file.txt
    assert visible[0].name == "adir"
    assert visible[1].name == "zdir"
    assert visible[2].name == "bfile.txt"
    assert visible[3].name == "file.txt"

def test_folders_first_sorting_by_name_descending():
    """Test folders-first with name sorting (descending) - CRITICAL FIX TEST."""
    now = datetime.now()
    entries = [
        lister.Entry(Path("/a/file.txt"), "file.txt", False, 100, now, now, now, 0),
        lister.Entry(Path("/a/zdir"), "zdir", True, 0, now, now, now, 0),
        lister.Entry(Path("/a/adir"), "adir", True, 0, now, now, now, 0),
        lister.Entry(Path("/a/bfile.txt"), "bfile.txt", False, 200, now, now, now, 0),
    ]
    manager = lister.ListerManager(entries, max_depth=0)

    # Get visible with dirs_first=True, descending
    visible = manager.get_visible_entries(lambda e: e.name.lower(), descending=True, dirs_first=True)

    # Folders should STILL come first, but sorted descending within their group
    # Should see: zdir, adir, file.txt, bfile.txt
    assert visible[0].name == "zdir"
    assert visible[1].name == "adir"
    assert visible[2].name == "file.txt"
    assert visible[3].name == "bfile.txt"

def test_folders_first_toggle_off():
    """Test that dirs_first=False mixes files and folders."""
    now = datetime.now()
    entries = [
        lister.Entry(Path("/a/file.txt"), "file.txt", False, 100, now, now, now, 0),
        lister.Entry(Path("/a/zdir"), "zdir", True, 0, now, now, now, 0),
        lister.Entry(Path("/a/adir"), "adir", True, 0, now, now, now, 0),
    ]
    manager = lister.ListerManager(entries, max_depth=0)

    # Get visible with dirs_first=False
    visible = manager.get_visible_entries(lambda e: e.name.lower(), descending=False, dirs_first=False)

    # Should see: adir, file.txt, zdir (all mixed by name)
    assert visible[0].name == "adir"
    assert visible[1].name == "file.txt"
    assert visible[2].name == "zdir"

def test_item_count_abbreviation():
    """Test item count abbreviation for large numbers."""
    now = datetime.now()

    # < 1000: show full number
    entry1 = lister.Entry(Path("/a"), "folder1", True, 0, now, now, now, 0, expanded=True, calculated_size=1000000, item_count=999)
    line1 = lister.format_entry_line(entry1, "created", 100, True, True, 0)
    assert "(999)" in line1

    # < 1000000: show "Nk"
    entry2 = lister.Entry(Path("/b"), "folder2", True, 0, now, now, now, 0, expanded=True, calculated_size=1000000, item_count=45282)
    line2 = lister.format_entry_line(entry2, "created", 100, True, True, 0)
    assert "(45k)" in line2

    # >= 1000000: show "N.NM"
    entry3 = lister.Entry(Path("/c"), "folder3", True, 0, now, now, now, 0, expanded=True, calculated_size=1000000, item_count=1234567)
    line3 = lister.format_entry_line(entry3, "created", 100, True, True, 0)
    assert "(1.2M)" in line3

def test_deep_nesting_size_display(temp_dir_structure: Path):
    """Test that size column is visible even with deep nesting."""
    # Create a deeply nested structure with long names
    deep = temp_dir_structure / "level1_very_long_folder_name_that_could_cause_issues"
    deep.mkdir()
    deeper = deep / "level2_another_extremely_long_folder_name_with_many_characters"
    deeper.mkdir()
    deepest = deeper / "level3_yet_another_absurdly_long_name_for_testing_purposes"
    deepest.mkdir()
    (deepest / "test_file_with_long_name.txt").write_text("x" * 1000)

    entries = lister.read_entries_recursive(temp_dir_structure, max_depth=5)

    # Format lines for deeply nested items with terminal width constraints
    for entry in entries:
        if entry.depth >= 2:
            # Use typical terminal width of 80
            line = lister.format_entry_line(entry, "created", 80, True, True, 0)
            # Line should not exceed 80 characters
            assert len(line) <= 80
            # Should still have content (not completely truncated)
            assert len(line) > 20
