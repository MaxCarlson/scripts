import pytest
import os
from pathlib import Path
from system_manager.manager import SystemManager

@pytest.fixture
def temp_files(tmp_path):
    # Create some files with different sizes and modification times
    f1 = tmp_path / "file1.txt"
    f1.write_text("Small file")
    
    f2 = tmp_path / "file2.log"
    f2.write_text("Large file content" * 100)
    
    # Nested file
    d1 = tmp_path / "subdir"
    d1.mkdir()
    f3 = d1 / "file3.txt"
    f3.write_text("Nested file")
    
    return tmp_path

def test_file_recent(temp_files):
    mgr = SystemManager()
    results = mgr.file_recent(directory=str(temp_files), count=5, recursive=True)
    assert len(results) >= 3
    assert any(r['name'] == "file1.txt" for r in results)
    assert any(r['name'] == "file3.txt" for r in results)

def test_file_largest(temp_files):
    mgr = SystemManager()
    results = mgr.file_largest(directory=str(temp_files), count=5, recursive=True)
    assert len(results) >= 3
    assert results[0]['name'] == "file2.log"  # Should be the largest

def test_file_size(temp_files):
    mgr = SystemManager()
    result = mgr.file_size(directory=str(temp_files), recursive=True)
    assert result['file_count'] >= 3
    assert result['bytes'] > 0
    assert "folder" in result

def test_file_rename_ext(temp_files):
    mgr = SystemManager()
    # Dry run first
    results = mgr.file_rename_ext(old_ext=".log", new_ext=".txt", directory=str(temp_files), recursive=False, apply=False)
    assert len(results) == 1
    assert results[0]['old'].endswith("file2.log")
    assert results[0]['new'].endswith("file2.txt")
    assert (temp_files / "file2.log").exists()
    
    # Apply
    mgr.file_rename_ext(old_ext=".log", new_ext=".txt", directory=str(temp_files), recursive=False, apply=True)
    assert not (temp_files / "file2.log").exists()
    assert (temp_files / "file2.txt").exists()

def test_file_add_prefix(temp_files):
    mgr = SystemManager()
    mgr.file_add_prefix(prefix="pre_", directory=str(temp_files), recursive=False, apply=True)
    assert (temp_files / "pre_file1.txt").exists()

def test_file_remove_empty_dirs(temp_files):
    mgr = SystemManager()
    empty_dir = temp_files / "empty"
    empty_dir.mkdir()
    results = mgr.file_remove_empty_dirs(directory=str(temp_files), apply=True)
    assert any("empty" in r['path'] for r in results)
    assert not empty_dir.exists()

def test_file_grep(temp_files):
    mgr = SystemManager()
    results = mgr.file_grep(pattern="Large", directory=str(temp_files), recursive=True)
    assert len(results) > 0
    assert any(r["path"].endswith("file2.log") for r in results)
    assert all({"path", "line", "line_number"} <= set(r) for r in results)
