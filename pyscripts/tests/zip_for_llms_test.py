import os
import zipfile
import pytest
import shutil
from pathlib import Path
from zip_for_llms import zip_folder, get_directory_size, delete_files_to_fit_size, flatten_directory

# Get the script path
#script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'zip_for_llms.py'))                                                                                                                                                        # Load the module dynamically
#spec = importlib.util.spec_from_file_location("zip_for_llms", script_path)
#git_sync = importlib.util.module_from_spec(spec)
#sys.modules["zip_for_llms"] = git_sync
#spec.loader.exec_module(git_sync)

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
    (root / "src" / "script.pyo").write_text("")  # Should be removed
    (root / "data" / "large.log").write_text("x" * (1024 * 1024 * 5))  # 5MB log file
    (root / "data" / "small.json").write_text("{}")  # Small file

    return root

def test_zip_creation(temp_test_dir, tmp_path):
    """Tests if the zip file is created correctly."""
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
    
    # Check that zip does NOT contain excluded files
    with zipfile.ZipFile(output_zip, 'r') as zipf:
        files = zipf.namelist()
        assert "src/script.py" in files
        assert "data/large.log" in files
        assert "src/script.pyo" not in files  # Should be excluded

def test_flatten_directory(temp_test_dir, tmp_path):
    """Tests the flattening of a directory."""
    temp_dir = flatten_directory(temp_test_dir, name_by_path=False)
    files = list(temp_dir.iterdir())

    assert len(files) == 3  # Only files should be moved
    assert (temp_dir / "script.py").exists()
    assert (temp_dir / "large.log").exists()
    assert not (temp_test_dir / "src/script.py").exists()  # Original should be gone

def test_zip_with_max_size(temp_test_dir, tmp_path):
    """Tests that the zip file respects the max size constraint."""
    output_zip = tmp_path / "limited.zip"
    
    zip_folder(
        source_dir=temp_test_dir,
        output_zip=output_zip,
        exclude_dirs=set(),
        exclude_exts=set(),
        exclude_files=set(),
        remove_patterns=[],
        keep_patterns=[],
        max_size=2,  # 2MB max
        preferences=[".log"],  # Prefer deleting log files first
        flatten=False,
        name_by_path=False,
        verbose=False
    )

    assert output_zip.exists()
    assert output_zip.stat().st_size <= 2 * 1024 * 1024  # Ensure it's under 2MB

def test_delete_files_to_fit_size(temp_test_dir):
    """Tests file deletion logic based on max size constraint."""
    delete_files_to_fit_size(temp_test_dir, target_size_mb=1, preferences=[".log", ".json"])
    assert not (temp_test_dir / "data/large.log").exists()  # Large log file should be deleted
    assert (temp_test_dir / "data/small.json").exists()  # Small JSON should be kept if possible

def test_zip_with_remove_patterns(temp_test_dir, tmp_path):
    """Tests that remove patterns delete the correct files."""
    output_zip = tmp_path / "remove_pattern.zip"
    
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

    with zipfile.ZipFile(output_zip, 'r') as zipf:
        files = zipf.namelist()
        assert "data/large.log" not in files  # Log file should be removed

def test_zip_with_post_hierarchy(temp_test_dir, tmp_path):
    """Tests if hierarchy file is correctly generated after processing."""
    hierarchy_file = temp_test_dir / "folder_structure.txt"

    zip_folder(
        source_dir=temp_test_dir,
        output_zip=tmp_path / "test_post_hierarchy.zip",
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

    assert hierarchy_file.exists()
    assert "Folder Structure" in hierarchy_file.read_text()

def test_zip_with_flatten_and_name_by_path(temp_test_dir, tmp_path):
    """Tests that flattening with renaming by path works correctly."""
    output_zip = tmp_path / "flattened.zip"
    
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

    with zipfile.ZipFile(output_zip, 'r') as zipf:
        files = zipf.namelist()
        assert "src_script.py" in files  # Renamed correctly
        assert "data_large.log" in files  # Renamed correctly

def test_zip_with_all_exclusions(temp_test_dir, tmp_path):
    """Tests exclusion of directories, extensions, and specific files."""
    output_zip = tmp_path / "all_exclusions.zip"

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

    with zipfile.ZipFile(output_zip, 'r') as zipf:
        files = zipf.namelist()
        assert "src/script.py" in files
        assert "data/large.log" not in files  # Should be excluded
        assert "data/small.json" not in files  # Explicitly excluded
