import os
import zipfile
import pytest
from pathlib import Path
from zip_for_llms import (
    zip_folder,
    get_directory_size,
    delete_files_to_fit_size,
    flatten_directory,
    text_file_mode,
)

@pytest.fixture
def temp_test_dir(tmp_path):
    """Creates a temporary test directory structure."""
    root = tmp_path / "test_repo"
    root.mkdir()

    # Create subdirectories
    (root / "src").mkdir()
    (root / "data").mkdir()
    (root / ".git").mkdir()
    
    # Create files
    (root / "src" / "script.py").write_text("print('Hello, World!')")
    (root / "src" / "script.pyo").write_text("")  # Should be excluded by default
    (root / "data" / "large.log").write_text("x" * (1024 * 1024 * 5))  # 5 MB log file
    (root / "data" / "small.json").write_text("{}")  # Small file

    return root

def test_zip_creation(temp_test_dir, tmp_path):
    """Tests zip_folder creates a zip and respects exclusions."""
    output_zip = tmp_path / "test_repo.zip"
    zip_folder(
        source_dir=temp_test_dir,
        output_zip=output_zip,
        exclude_dirs={".git"},
        exclude_exts={".pyo"},
        exclude_files=set(),
        remove_patterns=[],
        keep_patterns=[],
        max_size=None,
        preferences=[],
        flatten=False,
        name_by_path=False,
        verbose=False
    )
    assert output_zip.exists()
    with zipfile.ZipFile(output_zip, 'r') as z:
        names = z.namelist()
        assert "src/script.py" in names
        assert "data/large.log" in names
        assert "src/script.pyo" not in names

def test_flatten_directory(temp_test_dir, tmp_path):
    """Tests flatten_directory moves only non-excluded files."""
    flat = flatten_directory(temp_test_dir, name_by_path=False)
    files = list(flat.iterdir())
    # script.py, large.log, small.json moved; script.pyo excluded
    assert len(files) == 3
    assert (flat / "script.py").exists()
    assert (flat / "large.log").exists()
    assert (flat / "small.json").exists()
    # originals removed
    assert not (temp_test_dir / "src/script.py").exists()

def test_zip_with_max_size(temp_test_dir, tmp_path):
    """Tests zip_folder enforces max_size by pruning preferred extensions first."""
    output_zip = tmp_path / "limited.zip"
    zip_folder(
        source_dir=temp_test_dir,
        output_zip=output_zip,
        exclude_dirs=set(),
        exclude_exts=set(),
        exclude_files=set(),
        remove_patterns=[],
        keep_patterns=[],
        max_size=2,              # 2 MB limit
        preferences=[".log"],     # prune .log first
        flatten=False,
        name_by_path=False,
        verbose=False
    )
    assert output_zip.exists()
    assert output_zip.stat().st_size <= 2 * 1024 * 1024

def test_delete_files_to_fit_size(temp_test_dir):
    """Tests delete_files_to_fit_size removes large files based on preferences."""
    removed = delete_files_to_fit_size(temp_test_dir, target_size_mb=1, preferences=[".log", ".json"])
    assert any("large.log" in p for p in removed)
    assert (temp_test_dir / "data/small.json").exists()

def test_zip_with_remove_patterns(temp_test_dir, tmp_path):
    """Tests zip_folder remove_patterns excludes matching files."""
    output_zip = tmp_path / "rm_pat.zip"
    zip_folder(
        source_dir=temp_test_dir,
        output_zip=output_zip,
        exclude_dirs=set(),
        exclude_exts=set(),
        exclude_files=set(),
        remove_patterns=["*.log"],
        keep_patterns=[],
        max_size=None,
        preferences=[],
        flatten=False,
        name_by_path=False,
        verbose=False
    )
    with zipfile.ZipFile(output_zip, 'r') as z:
        assert "data/large.log" not in z.namelist()

def test_zip_with_post_hierarchy(temp_test_dir, tmp_path):
    """Tests folder_structure.txt is generated before zipping."""
    hier = temp_test_dir / "folder_structure.txt"
    zip_folder(
        source_dir=temp_test_dir,
        output_zip=tmp_path / "post_hier.zip",
        exclude_dirs=set(),
        exclude_exts=set(),
        exclude_files=set(),
        remove_patterns=[],
        keep_patterns=[],
        max_size=None,
        preferences=[],
        flatten=False,
        name_by_path=False,
        verbose=False
    )
    assert hier.exists()
    txt = hier.read_text()
    assert "Folder Structure" in txt
    assert "src/" in txt and "data/" in txt

def test_zip_with_flatten_and_name_by_path(temp_test_dir, tmp_path):
    """Tests flatten + name_by_path renames files correctly in the zip."""
    output_zip = tmp_path / "flat_name.zip"
    zip_folder(
        source_dir=temp_test_dir,
        output_zip=output_zip,
        exclude_dirs=set(),
        exclude_exts=set(),
        exclude_files=set(),
        remove_patterns=[],
        keep_patterns=[],
        max_size=None,
        preferences=[],
        flatten=True,
        name_by_path=True,
        verbose=False
    )
    with zipfile.ZipFile(output_zip, 'r') as z:
        names = z.namelist()
        assert "src_script.py" in names
        assert "data_large.log" in names

def test_zip_with_all_exclusions(temp_test_dir, tmp_path):
    """Tests combined exclusions for dirs, extensions, and specific files."""
    output_zip = tmp_path / "all_ex.zip"
    zip_folder(
        source_dir=temp_test_dir,
        output_zip=output_zip,
        exclude_dirs={".git"},
        exclude_exts={".log"},
        exclude_files={"small.json"},
        remove_patterns=[],
        keep_patterns=[],
        max_size=None,
        preferences=[],
        flatten=False,
        name_by_path=False,
        verbose=False
    )
    with zipfile.ZipFile(output_zip, 'r') as z:
        names = z.namelist()
        assert "src/script.py" in names
        assert "data/large.log" not in names
        assert "data/small.json" not in names

def test_file_mode_output(capsys, temp_test_dir, tmp_path):
    """Tests text_file_mode prints hierarchy, stats, and list of added files."""
    # add an extra file
    (temp_test_dir / "hello.txt").write_text("Hello World")
    out_txt = tmp_path / "out.txt"
    text_file_mode(
        source_dir=temp_test_dir,
        output_file=out_txt,
        exclude_dirs=set(),
        exclude_exts=set(),
        exclude_files=set(),
        remove_patterns=[],
        keep_patterns=[],
        flatten=False,
        name_by_path=False,
        verbose=False
    )
    # file exists and contains expected content
    assert out_txt.exists()
    content = out_txt.read_text()
    assert "Folder Structure" in content
    assert "-- File: hello.txt --" in content
    assert "Hello World" in content

    # stdout should include process stats
    out = capsys.readouterr().out
    assert "Hierarchy printed:" in out
    assert "Files processed:" in out
    assert "Files added:" in out
    assert "hello.txt" in out
    assert f"Created text file: {out_txt}" in out

def test_file_mode_verbose_skipped(capsys, temp_test_dir, tmp_path):
    """Tests verbose mode reports skipped files."""
    # add an excluded file
    (temp_test_dir / "ignore.tmp").write_text("ignore me")
    out2 = tmp_path / "out2.txt"
    text_file_mode(
        source_dir=temp_test_dir,
        output_file=out2,
        exclude_dirs=set(),
        exclude_exts={".tmp"},
        exclude_files=set(),
        remove_patterns=[],
        keep_patterns=[],
        flatten=False,
        name_by_path=False,
        verbose=True
    )
    out = capsys.readouterr().out
    assert "Skipped files:" in out
    assert "ignore.tmp" in out
    assert f"Created text file: {out2}" in out
