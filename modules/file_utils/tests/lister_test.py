
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
    formatted_line = lister.format_entry_line(entry, "created", 80)
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
    formatted_line = lister.format_entry_line(entry, "created", 80)
    # Check for 2 levels of indentation (4 spaces)
    assert "    file.txt" in formatted_line
