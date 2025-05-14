import os
import zipfile
import pytest
import shutil
from pathlib import Path
import datetime # For checking timestamp in LLM output, if we add it

# Assuming the modified script is named repo_processor.py and is in the same directory or accessible
from repo_processor import (
    zip_folder,
    generate_llm_text_output,
    DEFAULT_EXCLUDE_DIRS,
    DEFAULT_EXCLUDE_EXTS,
    DEFAULT_EXCLUDE_FILES,
    # For direct testing of helpers if needed, though better to test via main functions
    # get_directory_size,
    # delete_files_to_fit_size_in_dir,
    # flatten_directory_for_zip,
    # generate_directory_tree_string, # Can be complex to test in isolation perfectly
    # should_exclude
)

@pytest.fixture
def temp_repo_structure(tmp_path):
    """Creates a more complex temporary test directory structure."""
    repo_root = tmp_path / "sample_repo"
    repo_root.mkdir()

    # Common top-level files
    (repo_root / "README.md").write_text("# Sample Repo\nThis is a test.")
    (repo_root / ".gitignore").write_text("*.log\nnode_modules/\n.env\n/dist/\n")
    (repo_root / "package.json").write_text('{"name": "test-package"}')
    (repo_root / "package-lock.json").write_text('{}') # Should be excluded by default

    # Source directory
    src_dir = repo_root / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('hello from main.py')")
    (src_dir / "utils.js").write_text("function helper() {}")
    (src_dir / "config.important.json").write_text('{"key": "important_value"}') # To test keep_patterns

    # Module within src
    module_a = src_dir / "moduleA"
    module_a.mkdir()
    (module_a / "service.ts").write_text("export class Service {}")
    (module_a / "temp_data.tmp").write_text("temporary") # Should be excluded by default ext

    # Data directory with various files
    data_dir = repo_root / "data"
    data_dir.mkdir()
    (data_dir / "image.png").write_text("binary_data_png", encoding="utf-8") # Treat as text for test simplicity
    (data_dir / "archive.zip").write_text("binary_data_zip", encoding="utf-8")
    (data_dir / "report.log").write_text("Log line 1\nLog line 2") # Excluded by .gitignore and default ext

    # Excluded directories by default
    (repo_root / ".git").mkdir()
    (repo_root / ".git" / "config").write_text("[core]\nrepositoryformatversion = 0")
    (repo_root / "node_modules" / "some_lib" / "index.js").mkdir(parents=True, exist_ok=True)
    (repo_root / "node_modules" / "some_lib" / "index.js").write_text("// some lib code")
    
    # For testing remove_patterns
    temp_dir = repo_root / "temp_files"
    temp_dir.mkdir()
    (temp_dir / "a.bak").write_text("backup a")
    (temp_dir / "b.tmp").write_text("temp b") # Also excluded by default ext

    dist_dir = repo_root / "dist" # Excluded by .gitignore
    dist_dir.mkdir()
    (dist_dir / "bundle.js").write_text("minified_code")

    return repo_root

# --- ZIP Functionality Tests (can reuse/adapt some of your originals) ---
def test_zip_creation_basic(temp_repo_structure, tmp_path):
    output_zip = tmp_path / "repo.zip"
    zip_folder(
        source_dir_str=str(temp_repo_structure),
        output_zip_str=str(output_zip),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS),
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=[],
        max_size_mb=None,
        deletion_prefs_list=[],
        flatten_flag=False,
        name_by_path_flag=False,
        verbose=False
    )
    assert output_zip.exists()
    with zipfile.ZipFile(output_zip, 'r') as zf:
        namelist = zf.namelist()
        assert "README.md" in namelist
        assert "src/main.py" in namelist
        assert ".gitignore" in namelist # .gitignore is not a default excluded file name
        assert "package.json" in namelist

        # Check default exclusions
        assert not any(name.startswith(".git/") for name in namelist)
        assert not any(name.startswith("node_modules/") for name in namelist)
        assert "package-lock.json" not in namelist
        assert "src/moduleA/temp_data.tmp" not in namelist
        assert "data/report.log" not in namelist # default ext and gitignored
        assert "temp_files/b.tmp" not in namelist # default ext

def test_zip_with_flatten_and_name_by_path(temp_repo_structure, tmp_path):
    output_zip = tmp_path / "flattened_repo.zip"
    zip_folder(
        source_dir_str=str(temp_repo_structure),
        output_zip_str=str(output_zip),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS),
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=[],
        max_size_mb=None,
        deletion_prefs_list=[],
        flatten_flag=True,
        name_by_path_flag=True,
        verbose=True # Enable verbose to see temp dir creation/deletion
    )
    assert output_zip.exists()
    with zipfile.ZipFile(output_zip, 'r') as zf:
        namelist = zf.namelist()
        # Expected flattened names
        assert "README.md" in namelist # If at root, name doesn't change much
        assert "src_main.py" in namelist
        assert "src_moduleA_service.ts" in namelist
        assert "data_image.png" in namelist
        # Check that default excluded files are still not present even if flattened
        assert "package-lock.json" not in namelist # Assuming it's excluded before flattening
        assert not any("src_moduleA_temp_data.tmp" in name for name in namelist)


def test_zip_max_size_and_deletion_prefs(temp_repo_structure, tmp_path):
    # Make a large file to ensure deletion happens
    large_file_path = temp_repo_structure / "src" / "very_large_file.bin"
    large_file_path.write_text("x" * (3 * 1024 * 1024)) # 3MB

    output_zip = tmp_path / "sized_repo.zip"
    zip_folder(
        source_dir_str=str(temp_repo_structure),
        output_zip_str=str(output_zip),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS),
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=[],
        max_size_mb=1.0, # Target 1MB
        deletion_prefs_list=[".bin", ".png"], # Prefer deleting .bin, then .png
        flatten_flag=False, # Test deletion on original structure (via copy for temp processing if any)
        name_by_path_flag=False,
        verbose=True
    )
    assert output_zip.exists()
    zip_size_bytes = output_zip.stat().st_size
    # Allow for some overhead, but should be close to 1MB or less
    # This assertion depends heavily on compression ratio and what files are left.
    # The current delete_files_to_fit_size_in_dir prunes the source *before* zipping.
    assert zip_size_bytes < 1.5 * 1024 * 1024

    # Check if the large file was indeed targeted. Since deletion happens on a temp copy
    # or the source (if not flattening), we can't easily check the zip content for absence
    # without knowing exactly what remains. A better test might be to mock get_directory_size
    # or check verbose logs if the deletion function reports what it deleted.
    # For now, size check is the primary indicator.

# --- LLM Text Output Functionality Tests ---

@pytest.fixture
def llm_output_path(tmp_path):
    return tmp_path / "llm_repo_analysis.txt"

def test_llm_output_creation_basic(temp_repo_structure, llm_output_path):
    generate_llm_text_output(
        source_dir_path_str=str(temp_repo_structure),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS),
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=[],
        verbose=False
    )
    assert llm_output_path.exists()
    content = llm_output_path.read_text()

    assert "=== Repository Analysis: sample_repo ===" in content
    assert "**1. Full Directory Structure (filtered):**" in content
    assert "README.md" in content # Part of tree and content
    assert "src/" in content
    assert "main.py" in content # In tree
    assert "--- File: README.md ---" in content
    assert "# Sample Repo" in content
    assert "--- End of File: README.md ---" in content
    assert "--- File: src/main.py ---" in content
    assert "print('hello from main.py')" in content

    assert "**2. Contextual Files (Content Excluded or Unreadable):**" in content
    assert "package-lock.json (Reason: Excluded by rules" in content
    assert str(Path("src") / "moduleA" / "temp_data.tmp") + " (Reason: Excluded by rules" in content
    assert str(Path("data") / "report.log") + " (Reason: Excluded by rules" in content
    assert str(Path(".git") / "config") + " (Reason: Excluded by rules" in content # .git itself is excluded dir name
    assert str(Path("node_modules") / "some_lib" / "index.js") + " (Reason: Excluded by rules" in content


def test_llm_output_with_remove_patterns(temp_repo_structure, llm_output_path):
    generate_llm_text_output(
        source_dir_path_str=str(temp_repo_structure),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS),
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=["*.json", "**/temp_files/*"], # Remove all json, and all in temp_files
        keep_patterns_list=[],
        verbose=True
    )
    content = llm_output_path.read_text()

    assert "--- File: package.json ---" not in content # Removed by *.json
    assert "src/config.important.json (Reason: Excluded by rules" in content # Removed by *.json
    assert str(Path("temp_files") / "a.bak") + " (Reason: Excluded by rules" in content # Removed by pattern
    assert "--- File: src/main.py ---" in content # Should still be there

def test_llm_output_with_keep_patterns(temp_repo_structure, llm_output_path):
    generate_llm_text_output(
        source_dir_path_str=str(temp_repo_structure),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS), # .log is in DEFAULT_EXCLUDE_EXTS
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=["*.log", "src/config.important.json"], # Keep all logs and this specific json
        verbose=True
    )
    content = llm_output_path.read_text()

    assert "--- File: data/report.log ---" in content # Kept despite default ext exclusion
    assert "Log line 1" in content
    assert "--- File: src/config.important.json ---" in content # Kept
    assert '{"key": "important_value"}' in content

    # A file normally excluded by name should still be excluded if not kept
    assert "package-lock.json (Reason: Excluded by rules" in content


def test_llm_output_directory_tree_filtering(temp_repo_structure, llm_output_path):
    # Test that the directory tree string itself is filtered
    generate_llm_text_output(
        source_dir_path_str=str(temp_repo_structure),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS) + ["data"], # Exclude "data" dir by name
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=[],
        verbose=False
    )
    content = llm_output_path.read_text()
    
    # Find the directory structure section
    tree_section_start = content.find("**1. Full Directory Structure (filtered):**")
    tree_section_end = content.find("\n---\n", tree_section_start)
    tree_content = content[tree_section_start:tree_section_end]

    assert "sample_repo/" in tree_content
    assert "src/" in tree_content
    assert "data/" not in tree_content # Explicitly excluded
    assert ".git/" not in tree_content # Excluded by default
    assert "node_modules/" not in tree_content # Excluded by default

def test_llm_output_empty_repo(tmp_path, llm_output_path):
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    generate_llm_text_output(
        source_dir_path_str=str(empty_repo),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=[], exclude_exts_list=[], exclude_files_list=[],
        remove_patterns_list=[], keep_patterns_list=[], verbose=False
    )
    content = llm_output_path.read_text()
    assert "=== Repository Analysis: empty_repo ===" in content
    assert "No file content was included." in content
    assert "No files were specifically excluded from content" in content # or similar message
    assert "empty_repo/" in content # Tree should just show the root

# You can add more tests:
# - Conflicting keep/remove patterns (define expected behavior)
# - Very deep directory structures (if generate_directory_tree_string has depth limits)
# - Files with unusual characters in names or content (ensure encoding holds)
# - Permission denied errors during file access (how are they reported in LLM output?)
