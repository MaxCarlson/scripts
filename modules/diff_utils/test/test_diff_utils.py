import os
import pytest
import time

from dir_diff import DirectoryDiff

@pytest.fixture
def setup_directories(tmp_path):
    """
    Creates two temporary directories (src and dest) with a variety of files
    for testing the diff functionality.
    - A common file with identical content.
    - A file only in the source.
    - A file only in the destination.
    - A file with the same name but different content.
    - A nested directory with a file.
    """
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()
    
    # Create a common file with identical content.
    (src_dir / "common.txt").write_text("hello world")
    (dest_dir / "common.txt").write_text("hello world")
    
    # Create a file that exists only in src.
    (src_dir / "src_only.txt").write_text("only in src")
    
    # Create a file that exists only in dest.
    (dest_dir / "dest_only.txt").write_text("only in dest")
    
    # Create a file with the same name in both directories but with different content.
    (src_dir / "diff.txt").write_text("content A")
    (dest_dir / "diff.txt").write_text("content B")
    
    # Create a nested directory with a common file.
    src_sub = src_dir / "subdir"
    dest_sub = dest_dir / "subdir"
    src_sub.mkdir()
    dest_sub.mkdir()
    (src_sub / "nested.txt").write_text("nested content")
    (dest_sub / "nested.txt").write_text("nested content")
    
    return str(src_dir), str(dest_dir)

def test_compare_structure_and_files(setup_directories):
    """
    Test that DirectoryDiff correctly identifies items unique to each directory,
    common items, and files with content differences.
    """
    src, dest = setup_directories
    options = {
        "ignore_patterns": [],
        "dry_run": True,
        "verbose": True,
        "output_format": "plain",
        "checksum": "md5",
        "case_sensitive": True,
        "follow_symlinks": False,
        "threads": 1,
        "time_tolerance": 0,
        "mode": "diff",
        "interactive": False,
        "compare_metadata": True
    }
    diff = DirectoryDiff(src, dest, options)
    diff.compare_structures()
    diff.compare_files()
    
    # src_only should include "src_only.txt"
    assert "src_only.txt" in diff.diff_result["src_only"]
    
    # dest_only should include "dest_only.txt"
    assert "dest_only.txt" in diff.diff_result["dest_only"]
    
    # The common set should include "common.txt", "diff.txt" and the "subdir" entry.
    common = diff.diff_result["common"]
    assert "common.txt" in common
    assert "diff.txt" in common
    # Depending on the scan, the nested directory might be represented as "subdir" or "subdir/nested.txt".
    # We check that the "subdir" entry exists in the source structure.
    assert any(item.startswith("subdir") for item in diff.src_structure.keys())
    
    # diff.txt should be flagged as having a content difference.
    assert "diff.txt" in diff.diff_result["content_diff"]
    
    # common.txt should not be flagged for content differences.
    assert "common.txt" not in diff.diff_result["content_diff"]

def test_generate_report(setup_directories):
    """
    Run the diff process and verify that the generated report includes key sections.
    """
    src, dest = setup_directories
    options = {
        "ignore_patterns": [],
        "dry_run": True,
        "verbose": False,
        "output_format": "plain",
        "checksum": "md5",
        "case_sensitive": True,
        "follow_symlinks": False,
        "threads": 1,
        "time_tolerance": 0,
        "mode": "diff",
        "interactive": False,
        "compare_metadata": True
    }
    diff = DirectoryDiff(src, dest, options)
    diff.run()  # This calls compare functions and generates the report internally.
    report = diff.generate_report()
    
    # Check that key report sections appear.
    assert "=== Directory Diff Report ===" in report
    assert "Items only in source:" in report
    assert "Items only in destination:" in report
    assert "Files with content differences:" in report

def test_cli(monkeypatch, tmp_path, capsys):
    """
    Simulate a CLI run by setting sys.argv and invoking the main() function
    from the CLI script. The test verifies that output contains expected text.
    """
    # Create temporary src and dest directories with a common file.
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()
    (src_dir / "file.txt").write_text("same content")
    (dest_dir / "file.txt").write_text("same content")
    
    # Set sys.argv to simulate command-line arguments.
    cli_args = [
        "diff.py",
        "--source", str(src_dir),
        "--destination", str(dest_dir),
        "--output-format", "plain",
        "--dry-run",  # Ensure no file operations occur.
        "--verbose"
    ]
    monkeypatch.setattr("sys.argv", cli_args)
    
    # Import and run the CLI main function.
    from diff import main as cli_main
    cli_main()
    
    captured = capsys.readouterr().out
    # Verify that the output report contains key phrases.
    assert "Source Directory:" in captured
    assert "file.txt" in captured
