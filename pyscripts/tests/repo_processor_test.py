import os
import zipfile
import pytest
import shutil
from pathlib import Path
import datetime 

from repo_processor import (
    zip_folder,
    generate_llm_text_output,
    DEFAULT_EXCLUDE_DIRS,
    DEFAULT_EXCLUDE_EXTS,
    DEFAULT_EXCLUDE_FILES,
    DEFAULT_MAX_HIERARCHY_DEPTH
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
    (data_dir / "image.png").write_text("binary_data_png", encoding="utf-8") 
    (data_dir / "archive.zip").write_text("binary_data_zip", encoding="utf-8")
    (data_dir / "report.log").write_text("Log line 1\nLog line 2") # Excluded by .gitignore and default ext

    # Excluded directories by default
    git_dir = repo_root / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\nrepositoryformatversion = 0")
    
    node_modules_dir = repo_root / "node_modules"
    node_modules_dir.mkdir()
    some_lib_dir = node_modules_dir / "some_lib"
    some_lib_dir.mkdir(parents=True, exist_ok=True)
    (some_lib_dir / "index.js").write_text("// some lib code") # Fixed: write to file in dir
    
    # For testing remove_patterns
    temp_files_dir = repo_root / "temp_files"
    temp_files_dir.mkdir()
    (temp_files_dir / "a.bak").write_text("backup a")
    (temp_files_dir / "b.tmp").write_text("temp b") # Also excluded by default ext

    dist_dir = repo_root / "dist" 
    dist_dir.mkdir()
    (dist_dir / "bundle.js").write_text("minified_code")

    # An empty directory that might be excluded
    empty_excluded_dir = repo_root / "build" # 'build' is in DEFAULT_EXCLUDE_DIRS
    empty_excluded_dir.mkdir()


    return repo_root

# --- ZIP Functionality Tests ---
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
        verbose=False # Switch to True for debugging if needed
    )
    assert output_zip.exists()
    with zipfile.ZipFile(output_zip, 'r') as zf:
        namelist = sorted(zf.namelist()) # Sort for consistent comparison
        
        assert "README.md" in namelist
        assert str(Path("src") / "main.py") in namelist # Use Path for os-agnostic paths
        assert ".gitignore" in namelist 
        assert "package.json" in namelist

        # Check default exclusions
        assert not any(name.startswith(".git/") for name in namelist)
        assert not any(name.startswith("node_modules/") for name in namelist)
        assert "package-lock.json" not in namelist
        assert str(Path("src") / "moduleA" / "temp_data.tmp") not in namelist
        assert str(Path("data") / "report.log") not in namelist 
        assert str(Path("temp_files") / "b.tmp") not in namelist
        assert not any(name.startswith("build/") for name in namelist)
        assert not any(name.startswith("dist/") for name in namelist)


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
        verbose=False # Switch to True for debugging if needed
    )
    assert output_zip.exists()
    with zipfile.ZipFile(output_zip, 'r') as zf:
        namelist = zf.namelist()
        assert "README.md" in namelist 
        assert "src_main.py" in namelist
        assert "src_moduleA_service.ts" in namelist
        assert "data_image.png" in namelist
        
        assert "package-lock.json" not in namelist 
        assert "src_moduleA_temp_data.tmp" not in namelist # Check for original name if path based
        assert not any("node_modules_some_lib_index.js" in name for name in namelist) # Excluded dir content
        assert not any("git_config" in name for name in namelist) # Excluded dir content


def test_zip_max_size_and_deletion_prefs(temp_repo_structure, tmp_path):
    large_file_path = temp_repo_structure / "src" / "very_large_file.bin" # .bin is in default exclude exts
    large_file_path.write_text("x" * (3 * 1024 * 1024)) # 3MB
    
    # Add another large file with a preferred deletion extension
    another_large_pref_del = temp_repo_structure / "data" / "large_video.mp4"
    another_large_pref_del.write_text("y" * (2 * 1024 * 1024)) # 2MB

    output_zip = tmp_path / "sized_repo.zip"
    zip_folder(
        source_dir_str=str(temp_repo_structure),
        output_zip_str=str(output_zip),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS),
        exclude_exts_list=[ext for ext in DEFAULT_EXCLUDE_EXTS if ext != ".bin"], # Keep .bin for this test initially
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=[], # No keep patterns, so very_large_file.bin would normally be included
        max_size_mb=1.0, 
        deletion_prefs_list=[".mp4", ".bin"], # Prefer deleting .mp4, then .bin
        flatten_flag=False, 
        name_by_path_flag=False,
        verbose=True # Enable for debugging deletion
    )
    assert output_zip.exists()
    zip_size_bytes = output_zip.stat().st_size
    assert zip_size_bytes < 1.5 * 1024 * 1024 # Allow some overhead

    # Check that the largest, deletable files were targeted.
    # With flatten_flag=False, deletion happens on the original structure (or its temp copy if that was implemented for safety)
    # The test setup might need adjustment if we want to inspect the zip content for absence precisely,
    # as it depends on compression and other small files.
    # For now, the size check is primary. Verbose logs would show deletions.
    # Let's check if the specific large files are gone from the zip if possible
    # This is tricky because deletion happens on source_dir_to_zip_from before zipping.
    # If not flattening, source_dir_to_zip_from is source_dir_orig.
    # So the files should be absent from the zip.
    with zipfile.ZipFile(output_zip, 'r') as zf:
        namelist = zf.namelist()
        assert str(Path("src") / "very_large_file.bin") not in namelist
        assert str(Path("data") / "large_video.mp4") not in namelist


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
        max_tree_depth=DEFAULT_MAX_HIERARCHY_DEPTH,
        verbose=False # Switch to True for debugging
    )
    assert llm_output_path.exists()
    content = llm_output_path.read_text()

    assert "=== Repository Analysis: sample_repo ===" in content
    assert "**1. Full Directory Structure (filtered):**" in content
    assert "README.md" in content 
    assert "src/" in content
    assert "main.py" in content 
    assert "--- File: README.md ---" in content
    assert "# Sample Repo" in content
    assert "--- End of File: README.md ---" in content
    assert f"--- File: {Path('src/main.py')} ---" in content # OS-agnostic
    assert "print('hello from main.py')" in content

    assert "**2. Contextual Files (Content Excluded or Unreadable):**" in content
    assert "package-lock.json (Reason: Excluded by rules" in content
    assert str(Path("src") / "moduleA" / "temp_data.tmp") + " (Reason: Excluded by rules" in content
    assert str(Path("data") / "report.log") + " (Reason: Excluded by rules" in content
    # Files inside default excluded dirs should be listed as excluded by rules if os.walk even gets to them
    # The generate_llm_text_output os.walk prunes traversal into excluded dirs.
    # So, their contents won't appear in "excluded_for_listing" unless a keep_pattern made us look inside.
    # The default excluded dirs themselves won't be in the tree.
    # Let's verify they (and their content) are not in "Included Files" nor "Excluded Files listed"
    # unless a keep pattern overrides.
    assert str(Path(".git") / "config") not in content # Not listed as included, not listed as contextual
    assert str(Path("node_modules") / "some_lib" / "index.js") not in content
    assert str(Path("build")) not in content # excluded dir
    assert str(Path("dist") / "bundle.js") not in content # dist is excluded


def test_llm_output_with_remove_patterns(temp_repo_structure, llm_output_path):
    generate_llm_text_output(
        source_dir_path_str=str(temp_repo_structure),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS),
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=["*.json", "**/temp_files/*"], 
        keep_patterns_list=[],
        max_tree_depth=DEFAULT_MAX_HIERARCHY_DEPTH,
        verbose=False # Switch to True for debugging
    )
    content = llm_output_path.read_text()

    assert "--- File: package.json ---" not in content 
    assert "package.json (Reason: Excluded by rules" in content # Now listed as excluded due to remove_pattern
    assert str(Path("src") / "config.important.json") + " (Reason: Excluded by rules" in content
    assert str(Path("temp_files") / "a.bak") + " (Reason: Excluded by rules" in content
    assert f"--- File: {Path('src/main.py')} ---" in content 

def test_llm_output_with_keep_patterns(temp_repo_structure, llm_output_path):
    # Add a normally excluded file inside an excluded dir to test if keep can retrieve it
    (temp_repo_structure / ".git" / "keep_this.txt").write_text("Secret keeper")

    generate_llm_text_output(
        source_dir_path_str=str(temp_repo_structure),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS), 
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=["*.log", str(Path("src") / "config.important.json"), str(Path(".git") / "keep_this.txt")], 
        max_tree_depth=DEFAULT_MAX_HIERARCHY_DEPTH,
        verbose=True # Debugging this
    )
    content = llm_output_path.read_text()

    assert f"--- File: {Path('data/report.log')} ---" in content 
    assert "Log line 1" in content
    assert f"--- File: {Path('src/config.important.json')} ---" in content 
    assert '{"key": "important_value"}' in content
    assert f"--- File: {Path('.git/keep_this.txt')} ---" in content # Kept despite being in .git
    assert "Secret keeper" in content

    assert "package-lock.json (Reason: Excluded by rules" in content


def test_llm_output_directory_tree_filtering(temp_repo_structure, llm_output_path):
    generate_llm_text_output(
        source_dir_path_str=str(temp_repo_structure),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS) + ["data"], # Exclude "data" dir by name
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=[],
        max_tree_depth=DEFAULT_MAX_HIERARCHY_DEPTH,
        verbose=False
    )
    content = llm_output_path.read_text()
    
    tree_section_start = content.find("**1. Full Directory Structure (filtered):**")
    tree_section_end = content.find("\n---\n", tree_section_start)
    tree_content = content[tree_section_start:tree_section_end]

    assert "sample_repo/" in tree_content
    assert "src/" in tree_content
    assert "data/" not in tree_content # Explicitly excluded
    assert ".git/" not in tree_content # Excluded by default
    assert "node_modules/" not in tree_content # Excluded by default
    assert "build/" not in tree_content # Excluded by default

def test_llm_output_empty_repo(tmp_path, llm_output_path):
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    generate_llm_text_output(
        source_dir_path_str=str(empty_repo),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=[], exclude_exts_list=[], exclude_files_list=[],
        remove_patterns_list=[], keep_patterns_list=[], 
        max_tree_depth=DEFAULT_MAX_HIERARCHY_DEPTH,
        verbose=False
    )
    content = llm_output_path.read_text()
    assert "=== Repository Analysis: empty_repo ===" in content
    assert "No file content was included." in content
    assert "No files were specifically excluded from content" in content 
    assert "empty_repo/" in content 
    assert "└── [No processable content or all items excluded]" in content

def test_llm_max_tree_depth(temp_repo_structure, llm_output_path):
    generate_llm_text_output(
        source_dir_path_str=str(temp_repo_structure),
        output_file_path_str=str(llm_output_path),
        exclude_dirs_list=list(DEFAULT_EXCLUDE_DIRS),
        exclude_exts_list=list(DEFAULT_EXCLUDE_EXTS),
        exclude_files_list=list(DEFAULT_EXCLUDE_FILES),
        remove_patterns_list=[],
        keep_patterns_list=[],
        max_tree_depth=1, # Only show root and its direct children
        verbose=False
    )
    content = llm_output_path.read_text()
    tree_section_start = content.find("**1. Full Directory Structure (filtered):**")
    tree_section_end = content.find("\n---\n", tree_section_start)
    tree_content = content[tree_section_start:tree_section_end]

    assert "sample_repo/" in tree_content
    assert "├── README.md" in tree_content # Direct child
    assert "├── .gitignore" in tree_content # Direct child
    assert "└── src/" in tree_content or "├── src/" in tree_content # Direct child, might be last or not depending on sort
    assert "main.py" not in tree_content # Grandchild, should not be listed due to depth=1

