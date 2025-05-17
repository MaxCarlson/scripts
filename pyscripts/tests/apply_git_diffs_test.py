import os
import re
import sys
import io
import tempfile
import pytest

# Import functions from your script.
# Adjust the module name if necessary.
import apply_git_diffs
from apply_git_diffs import (
    extract_hunks,
    apply_hunk,
    apply_unified_diff,
    apply_diff_to_file,
    parse_diff_and_apply,
    main_testable,
    # get_output_copy_path # Not typically tested directly, but used by the script
)

# For testing purposes, we override debug_utils in the module to avoid side effects.
class DummyDebugUtils:
    @staticmethod
    def write_debug(message="", channel="Debug", **kwargs):
        # Uncomment to see debug output during testing:
        # print(f"[{channel}] {message}")
        pass

    DEFAULT_LOG_DIR = os.path.join(tempfile.gettempdir(), "logs")

    @staticmethod
    def set_log_verbosity(level):
        pass

    @staticmethod
    def set_console_verbosity(level):
        pass

    @staticmethod
    def set_log_directory(path):
        pass

    @staticmethod
    def enable_file_logging():
        pass

apply_git_diffs.debug_utils = DummyDebugUtils

# -----------------------
# Unit Tests (Using tmp_path)
# -----------------------

def test_extract_hunks_single():
    """Test extraction of a single hunk from diff lines."""
    diff_lines = [
        "@@ -1,3 +1,3 @@",
        " line unchanged",
        "-line removed",
        "+line added",
        " line unchanged",
    ]
    hunks = extract_hunks(diff_lines)
    assert len(hunks) == 1
    assert hunks[0][0] == "@@ -1,3 +1,3 @@"
    assert hunks[0][1] == " line unchanged"
    assert hunks[0][2] == "-line removed"
    assert hunks[0][3] == "+line added"
    assert hunks[0][4] == " line unchanged"

def test_extract_hunks_multiple():
    """Test extraction of multiple hunks."""
    diff_lines = [
        "@@ -1,2 +1,2 @@",
        " line1",
        "-old line2",
        "+new line2",
        "@@ -4,2 +4,2 @@",
        " line4",
        "-old line5",
        "+new line5",
    ]
    hunks = extract_hunks(diff_lines)
    assert len(hunks) == 2
    assert hunks[0][0] == "@@ -1,2 +1,2 @@"
    assert hunks[1][0] == "@@ -4,2 +4,2 @@"

def test_apply_hunk_simple():
    """Test applying a simple hunk that replaces one line."""
    original_lines = ["line1\n", "line2\n", "line3\n"]
    hunk = [
        "@@ -2,1 +2,1 @@",
        "-line2",
        "+modified line2",
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["line1\n", "modified line2\n", "line3\n"]
    assert new_lines == expected

def test_apply_hunk_with_context():
    """Test applying a hunk that includes context lines."""
    original_lines = ["a\n", "b\n", "c\n", "d\n"]
    hunk = [
        "@@ -2,2 +2,2 @@",
        " b",
        "-c",
        "+C_modified",
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["a\n", "b\n", "C_modified\n", "d\n"]
    assert new_lines == expected

def test_apply_unified_diff_no_hunks():
    """Test applying a diff with no hunks returns original lines."""
    original_lines = ["a\n", "b\n", "c\n"]
    diff_content = "Some header info\nSome more header info\n"
    new_lines = apply_unified_diff(original_lines, diff_content)
    assert new_lines == original_lines

def test_apply_unified_diff_normal():
    """Test applying a unified diff with a valid hunk."""
    original_lines = ["line1\n", "line2\n", "line3\n"]
    diff_content = (
        "diff --git a/file.txt b/file.txt\n"
        "index 83db48f..f735c70 100644\n"
        "--- a/file.txt\n"
        "+++ b/file.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+modified line2\n"
        " line3\n"
    )
    new_lines = apply_unified_diff(original_lines, diff_content)
    expected = ["line1\n", "modified line2\n", "line3\n"]
    assert new_lines == expected

def test_apply_diff_to_file_nonexistent(tmp_path):
    """Test apply_diff_to_file on a non-existent file (treat as empty)."""
    file_path = tmp_path / "nonexistent.txt"
    diff_content = (
        "--- a/nonexistent.txt\n" 
        "+++ b/nonexistent.txt\n"
        "@@ -0,0 +1,2 @@\n"
        "+first line\n"
        "+second line\n"
    )
    # Updated call: apply_diff_to_file(read_filepath, diff_content, dry_run, effective_write_filepath)
    new_content = apply_diff_to_file(str(file_path), diff_content, False, str(file_path))
    assert new_content == "first line\nsecond line\n"
    with open(file_path, 'r', encoding='utf-8') as f:
        content_on_disk = f.read()
    assert content_on_disk == "first line\nsecond line\n"


def test_apply_diff_to_file_existing(tmp_path):
    """Test applying a diff to an existing file."""
    file_path = tmp_path / "file.txt"
    original_content = "line1\nline2\nline3\n"
    file_path.write_text(original_content, encoding='utf-8')
    diff_content = (
        "--- a/file.txt\n"
        "+++ b/file.txt\n"
        "@@ -2,1 +2,1 @@\n"
        "-line2\n"
        "+modified line2\n"
    )
    # Updated call
    new_content = apply_diff_to_file(str(file_path), diff_content, False, str(file_path))
    expected = "line1\nmodified line2\nline3\n"
    assert new_content == expected
    assert file_path.read_text(encoding='utf-8') == expected

def test_parse_diff_and_apply_valid(tmp_path):
    """Test parse_diff_and_apply with a valid diff block."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "test.txt"
    file_path = target_dir / file_rel_path
    file_path.write_text("a\nb\nc\n", encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        "index 0000001..0000002 100644\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,3 +1,3 @@\n"
        " a\n"
        "-b\n"
        "+B_modified\n"
        " c\n"
    )
    # Updated call: parse_diff_and_apply(diff_text, target_directory, dry_run, output_copy)
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert file_rel_path in modified
    expected = "a\nB_modified\nc\n"
    assert modified[file_rel_path] == expected
    assert file_path.read_text(encoding='utf-8') == expected

def test_parse_diff_and_apply_no_hunks(tmp_path):
    """Test parse_diff_and_apply with a diff block missing hunks."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "test.txt"
    (target_dir / file_rel_path).write_text("line1\nline2\n", encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "Some header text\n" # No '@@' hunks
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}


def test_parse_diff_and_apply_invalid_block(tmp_path):
    """Test parse_diff_and_apply with an invalid diff block (missing file markers)."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    diff_text = (
        "diff --git a/missing.txt b/missing.txt\n"
        "Some invalid diff content without proper ---/+++ lines\n"
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}

# -----------------------
# Tests for Main Functionality (main_testable)
# -----------------------

class MockArgs: 
    def __init__(self, directory, input, log_level="Debug", console_log_level="Debug", 
                 enable_file_log=False, log_dir="logs", force=False, # force is legacy from some edits, not used by current script
                 dry_run=False, output_copy=False): # Added new args with defaults
        self.directory = directory
        self.input = input 
        self.log_level = log_level
        self.console_log_level = console_log_level
        self.enable_file_log = enable_file_log
        self.log_dir = log_dir
        self.force = force 
        self.dry_run = dry_run
        self.output_copy = output_copy


def test_main_testable_with_direct_diff(tmp_path):
    """Test main_testable using direct diff text input."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "file.txt"
    file_path = target_dir / file_rel_path
    file_path.write_text("old line\n", encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        "index 0000001..0000002 100644\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-old line\n"
        "+new line\n"
    )
    # MockArgs will use default dry_run=False, output_copy=False
    args = MockArgs(directory=str(target_dir), input=diff_text) 
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "new line\n"
    assert file_path.read_text(encoding="utf-8") == "new line\n"

def test_main_testable_no_diff_input(tmp_path):
    """Test main_testable when no diff input is provided."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    args = MockArgs(directory=str(target_dir), input="")
    result = main_testable(args)
    assert "warning" in result
    assert result["warning"] == "No diff input provided."

def test_main_testable_from_file(tmp_path):
    """Test main_testable when diff input is provided via a file."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "patch.txt" 
    file_to_patch_path = target_dir / file_rel_path 
    file_to_patch_path.write_text("original\n", encoding="utf-8")
    
    diff_input_file = tmp_path / "diff.txt" 
    diff_content = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-original\n"
        "+modified\n"
    )
    diff_input_file.write_text(diff_content, encoding="utf-8")
    args = MockArgs(directory=str(target_dir), input=str(diff_input_file))
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "modified\n"
    assert file_to_patch_path.read_text(encoding="utf-8") == "modified\n"


def test_main_testable_clipboard_fallback(monkeypatch, tmp_path):
    """Test main_testable simulating clipboard input fallback."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "file.txt"
    file_path = target_dir / file_rel_path
    file_path.write_text("foo\n", encoding="utf-8")
    diff_text_for_stdin = ( 
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-foo\n"
        "+bar\n"
    )
    def fake_clipboard_get_clipboard_error(): 
        raise ImportError("Simulated clipboard error") 
    
    monkeypatch.setattr(apply_git_diffs.clipboard, "get_clipboard", fake_clipboard_get_clipboard_error)
    
    original_stdin = sys.stdin
    sys.stdin = io.StringIO(diff_text_for_stdin)
    
    args = MockArgs(directory=str(target_dir), input="clipboard") 
    
    try:
        result = main_testable(args)
    finally:
        sys.stdin = original_stdin

    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "bar\n"
    assert file_path.read_text(encoding="utf-8") == "bar\n"

# -----------------------
# Additional Tests for New Scenarios
# -----------------------

def test_parse_and_apply_multiple_valid_diffs(tmp_path):
    """
    Test applying a diff text that contains multiple valid diff blocks
    for different files. Expect that all diffs are applied.
    """
    target_dir = tmp_path 
    
    file1_rel = "file1.txt"
    file2_rel = "subdir/file2.txt" 
    
    file1_path = target_dir / file1_rel
    
    subdir = target_dir / "subdir"
    subdir.mkdir()
    file2_path = subdir / "file2.txt" 
    
    file1_path.write_text("Line1A\nLine1B\n", encoding="utf-8")
    file2_path.write_text("Line2A\nLine2B\n", encoding="utf-8")
    
    diff_text = (
        f"diff --git a/{file1_rel} b/{file1_rel}\n"
        f"--- a/{file1_rel}\n"
        f"+++ b/{file1_rel}\n"
        "@@ -1,2 +1,2 @@\n"
        "-Line1A\n"
        "+Modified Line1A\n"
        " Line1B\n"
        f"diff --git a/{file2_rel} b/{file2_rel}\n" 
        f"--- a/{file2_rel}\n"
        f"+++ b/{file2_rel}\n"
        "@@ -1,2 +1,2 @@\n"
        "-Line2A\n"
        "+Modified Line2A\n"
        " Line2B\n"
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert file1_rel in modified
    assert file2_rel in modified
    assert modified[file1_rel] == "Modified Line1A\nLine1B\n"
    assert modified[file2_rel] == "Modified Line2A\nLine2B\n"
    assert file1_path.read_text(encoding='utf-8') == "Modified Line1A\nLine1B\n"
    assert file2_path.read_text(encoding='utf-8') == "Modified Line2A\nLine2B\n"


def test_parse_and_apply_multiple_with_invalid_diff(tmp_path):
    """
    Test that if multiple diff blocks are passed and one is invalid,
    then no diffs should be applied (transactional behavior).
    """
    target_dir = tmp_path
    file_rel = "file1.txt"
    file_path = target_dir / file_rel
    file_path.write_text("Original\n", encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel} b/{file_rel}\n"
        f"--- a/{file_rel}\n"
        f"+++ b/{file_rel}\n"
        "@@ -1,1 +1,1 @@\n" 
        "-Original\n"
        "+Modified\n"
        "\n"
        "diff --git a/invalid.txt b/invalid.txt\n"
        "--- /dev/null\n" # Make it a bit more structured to ensure it's the content check
        "+++ b/invalid.txt\n"
        "Some random text that does not conform to diff format\n" 
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {} 
    assert file_path.read_text(encoding="utf-8") == "Original\n"

def test_parse_and_apply_diff_file_not_found(tmp_path):
    """
    Test that if a diff block targets a file not present in the target directory,
    and it's not a new file diff, then that diff is skipped.
    Other valid diffs in the same input should still be applied.
    """
    target_dir = tmp_path
    file_rel_exists = "exists.txt"
    file_path_exists = target_dir / file_rel_exists
    file_path_exists.write_text("content exists\n", encoding="utf-8")

    file_rel_nonexistent = "nonexistent.txt" 

    diff_text = (
        f"diff --git a/{file_rel_exists} b/{file_rel_exists}\n"
        f"--- a/{file_rel_exists}\n"
        f"+++ b/{file_rel_exists}\n"
        "@@ -1,1 +1,1 @@\n"
        "-content exists\n"
        "+content modified\n"
        f"diff --git a/{file_rel_nonexistent} b/{file_rel_nonexistent}\n"
        f"--- a/{file_rel_nonexistent}\n" 
        f"+++ b/{file_rel_nonexistent}\n"
        "@@ -1,1 +1,1 @@\n" 
        "-NonExistentOld\n"
        "+NonExistentNew\n"
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    
    assert file_rel_exists in modified 
    assert modified[file_rel_exists] == "content modified\n"
    assert file_rel_nonexistent not in modified 

# NEW TESTS FOR MULTI-HUNK SCENARIOS
def test_apply_unified_diff_multiple_hunks_line_count_change():
    """
    Tests applying a diff with multiple hunks to the same file, where the first
    hunk changes the line count.
    """
    original_lines = [
        "Line A\n", "Line B\n", "Line C\n", "Line D\n",
        "Line E\n", "Line F\n", "Line G\n", "Line H\n",
    ]
    diff_content = (
        "--- a/testfile.txt\n"
        "+++ b/testfile.txt\n"
        "@@ -2,2 +2,3 @@\n"
        "-Line B\n"
        "+Line B MODIFIED\n"
        "+Line B.5 ADDED\n"
        " Line C\n"
        "@@ -6,1 +7,1 @@\n"
        "-Line F\n"
        "+Line F MODIFIED\n"
    )
    expected_new_lines = [
        "Line A\n", "Line B MODIFIED\n", "Line B.5 ADDED\n", "Line C\n",
        "Line D\n", "Line E\n", "Line F MODIFIED\n", "Line G\n", "Line H\n",
    ]
    actual_new_lines = apply_unified_diff(original_lines, diff_content)
    assert actual_new_lines == expected_new_lines

def test_apply_diff_to_file_multiple_hunks_line_count_change(tmp_path):
    """
    Tests apply_diff_to_file with a multi-hunk diff where the first hunk
    alters line counts, verifying the final file content.
    """
    file_path = tmp_path / "testfile_multihunk.txt"
    original_content_str = (
        "Line A\nLine B\nLine C\nLine D\n"
        "Line E\nLine F\nLine G\nLine H\n"
    )
    file_path.write_text(original_content_str, encoding='utf-8')
    diff_content = (
        "--- a/testfile_multihunk.txt\n"
        "+++ b/testfile_multihunk.txt\n"
        "@@ -2,2 +2,3 @@\n"
        "-Line B\n"
        "+Line B MODIFIED\n"
        "+Line B.5 ADDED\n"
        " Line C\n"
        "@@ -6,1 +7,1 @@\n"
        "-Line F\n"
        "+Line F MODIFIED\n"
    )
    expected_content_str = (
        "Line A\nLine B MODIFIED\nLine B.5 ADDED\nLine C\n"
        "Line D\nLine E\nLine F MODIFIED\nLine G\nLine H\n"
    )
    # Updated call
    new_content_str = apply_diff_to_file(str(file_path), diff_content, False, str(file_path))
    assert new_content_str == expected_content_str
    assert file_path.read_text(encoding='utf-8') == expected_content_str

# NEW TESTS FOR UNSUPPORTED DIFF TYPES
def test_parse_and_apply_binary_file_diff(tmp_path):
    """Test that binary file diffs are recognized as unsupported."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "binary_file.dat"
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        "index 0000001..0000002 100644\n" 
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "Binary files a/binary_file.dat and b/binary_file.dat differ\n"
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should return empty dict for unsupported binary diff"

def test_parse_and_apply_file_mode_change_only_diff(tmp_path):
    """Test that file mode change-only diffs (no content hunks) are recognized as unsupported."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "script.sh"
    (target_dir / file_rel_path).write_text("#!/bin/bash\necho hello\n", encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n" 
        f"+++ b/{file_rel_path}\n"
        "old mode 100644\n"
        "new mode 100755\n"
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should return empty dict for mode-change-only diff without content hunks"

def test_parse_and_apply_symlink_diff(tmp_path):
    """Test that symbolic link diffs (mode 120000) are recognized as unsupported."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "my_link"
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        "new file mode 120000\n" 
        "index 0000000..ea61be9\n" 
        f"--- /dev/null\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -0,0 +1 @@\n" 
        "+../target_file\n" 
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should return empty dict for symlink diff due to mode 120000"

def test_parse_and_apply_rename_diff(tmp_path):
    """Test that file rename diffs (with 'rename from/to') are recognized as unsupported."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    old_file_rel_path = "old_name.txt"
    new_file_rel_path = "new_name.txt"
    diff_text = (
        f"diff --git a/{old_file_rel_path} b/{new_file_rel_path}\n"
        f"rename from {old_file_rel_path}\n"
        f"rename to {new_file_rel_path}\n"
        f"--- a/{old_file_rel_path}\n" 
        f"+++ b/{new_file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n" 
        "-a\n"
        "+b\n"
    )
    # Updated call
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should return empty dict for rename diff"

# NEW TESTS FOR --dry-run and --output-copy
def test_dry_run_does_not_modify_file(tmp_path):
    """Test that --dry-run prevents file modification."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "dry_run_test.txt"
    original_file_path = target_dir / file_rel_path
    original_content = "Original line 1\nOriginal line 2\n"
    original_file_path.write_text(original_content, encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,2 +1,2 @@\n"
        " Original line 1\n"
        "-Original line 2\n"
        "+Modified line 2\n"
    )
    args = MockArgs(directory=str(target_dir), input=diff_text, dry_run=True, output_copy=False)
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "Original line 1\nModified line 2\n"
    assert original_file_path.read_text(encoding="utf-8") == original_content

def test_dry_run_new_file_not_created(tmp_path):
    """Test that --dry-run prevents new file creation."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "new_dry_run_file.txt"
    new_file_path = target_dir / file_rel_path
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- /dev/null\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -0,0 +1,1 @@\n"
        "+This is a new file.\n"
    )
    args = MockArgs(directory=str(target_dir), input=diff_text, dry_run=True, output_copy=False)
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "This is a new file.\n"
    assert not new_file_path.exists()

def test_output_copy_existing_file(tmp_path):
    """Test --output-copy when the target file exists."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "output_copy_test.txt"
    original_file_path = target_dir / file_rel_path
    original_content = "Line 1 original\nLine 2 to change\n"
    original_file_path.write_text(original_content, encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -2,1 +2,1 @@\n"
        "-Line 2 to change\n"
        "+Line 2 MODIFIED\n"
    )
    args = MockArgs(directory=str(target_dir), input=diff_text, dry_run=False, output_copy=True)
    result = main_testable(args)
    expected_patched_content = "Line 1 original\nLine 2 MODIFIED\n"
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == expected_patched_content
    assert original_file_path.read_text(encoding="utf-8") == original_content
    
    name_part, ext_part = os.path.splitext(file_rel_path)
    actual_name_for_suffix = name_part
    if file_rel_path.startswith(".") and not ext_part: # Handles .filename
        actual_name_for_suffix = file_rel_path
        ext_part = ""
    elif not ext_part and name_part == file_rel_path: # Handles filename_no_ext
        actual_name_for_suffix = file_rel_path
        # ext_part is already ""

    expected_copy_filename = f"{actual_name_for_suffix}_applied_diff1{ext_part}"
    copied_file_path = target_dir / expected_copy_filename
    assert copied_file_path.exists(), f"Copied file '{expected_copy_filename}' should exist. Found: {list(target_dir.iterdir())}"
    assert copied_file_path.read_text(encoding="utf-8") == expected_patched_content

def test_output_copy_new_file(tmp_path):
    """Test --output-copy when the target is a new file from the diff."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "new_output_copy.txt" 
    original_file_path_if_not_copied = target_dir / file_rel_path
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- /dev/null\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -0,0 +1,2 @@\n"
        "+New file line 1.\n"
        "+New file line 2.\n"
    )
    args = MockArgs(directory=str(target_dir), input=diff_text, dry_run=False, output_copy=True)
    result = main_testable(args)
    expected_patched_content = "New file line 1.\nNew file line 2.\n"
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"] 
    assert result["modified_files"][file_rel_path] == expected_patched_content
    assert not original_file_path_if_not_copied.exists()

    name_part, ext_part = os.path.splitext(file_rel_path)
    actual_name_for_suffix = name_part
    if file_rel_path.startswith(".") and not ext_part: # Handles .filename
        actual_name_for_suffix = file_rel_path
        ext_part = ""
    elif not ext_part and name_part == file_rel_path: # Handles filename_no_ext
        actual_name_for_suffix = file_rel_path
        # ext_part is already ""
        
    expected_copy_filename = f"{actual_name_for_suffix}_applied_diff1{ext_part}"
    copied_file_path = target_dir / expected_copy_filename
    assert copied_file_path.exists()
    assert copied_file_path.read_text(encoding="utf-8") == expected_patched_content

def test_output_copy_creates_sequential_names(tmp_path):
    """Test that --output-copy creates _applied_diffN sequentially."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "sequential_test.txt"
    original_file_path = target_dir / file_rel_path
    original_file_path.write_text("original", encoding="utf-8")

    name_part, ext_part = os.path.splitext(file_rel_path)
    actual_name_for_suffix = name_part
    if file_rel_path.startswith(".") and not ext_part:
        actual_name_for_suffix = file_rel_path
        ext_part = ""
    elif not ext_part and name_part == file_rel_path:
        actual_name_for_suffix = file_rel_path
        
    pre_existing_copy_path = target_dir / f"{actual_name_for_suffix}_applied_diff1{ext_part}"
    pre_existing_copy_path.write_text("already here", encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-original\n"
        "+modified\n"
    )
    args = MockArgs(directory=str(target_dir), input=diff_text, dry_run=False, output_copy=True)
    main_testable(args) 
    expected_copy2_filename = f"{actual_name_for_suffix}_applied_diff2{ext_part}"
    copied_file2_path = target_dir / expected_copy2_filename
    assert copied_file2_path.exists()
    assert copied_file2_path.read_text(encoding="utf-8") == "modified\n"
    assert original_file_path.read_text(encoding="utf-8") == "original"
    assert pre_existing_copy_path.read_text(encoding="utf-8") == "already here"

# -----------------------
# Edge Case Tests
# -----------------------

def test_apply_hunk_invalid_header():
    """Test apply_hunk with an invalid hunk header (should leave file unchanged)."""
    original_lines = ["line1\n", "line2\n"]
    hunk = [
        "INVALID HEADER",
        "-line2",
        "+new line2",
    ]
    new_lines = apply_hunk(original_lines, hunk)
    assert new_lines == original_lines

def test_apply_diff_to_file_invalid_diff(tmp_path): 
    """Test apply_diff_to_file with diff input that does not contain hunks."""
    file_path_obj = tmp_path / "invalid_diff_test.txt" 
    original_file_content = "line1\nline2\n"
    file_path_obj.write_text(original_file_content, encoding="utf-8")
    
    filename = str(file_path_obj)
    diff_content_invalid = "Not a diff\nNo hunk info here\n" 
    # Updated call
    result_content = apply_diff_to_file(filename, diff_content_invalid, False, filename)
    
    assert result_content == original_file_content
    content_on_disk = file_path_obj.read_text(encoding="utf-8")
    assert content_on_disk == original_file_content

if __name__ == "__main__":
    pytest.main()
