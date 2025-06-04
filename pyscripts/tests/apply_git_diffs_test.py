# File: tests/apply_git_diffs_test.py
import os
import re
import sys
import io
import tempfile
import pytest
from pathlib import Path # Added for modern path handling

# Import functions from your script.
import apply_git_diffs # This will use the stubbed debug_utils
from apply_git_diffs import (
    extract_hunks,
    apply_hunk,
    apply_unified_diff,
    apply_diff_to_file,
    parse_diff_and_apply,
    main_testable,
    get_path_from_diff_header_line # Added import
)


class DummyDebugUtils:
    log_messages = [] 
    # New: Store structured log info if needed for complex assertions
    # For this test, just ensuring the exception string is appended is enough.
    # We could make log_messages a list of dicts: [{'channel': ..., 'message': ..., 'exception_str': ...}]

    @classmethod
    def write_debug(cls, message="", channel="Debug", **kwargs):
        log_entry = f"[{channel}] {message}"
        exc_info_val = kwargs.get('exc_info')
        
        if exc_info_val:
            if isinstance(exc_info_val, Exception):
                # Append the type and string of the exception to the message for easier checking
                log_entry += f" (Exception: {type(exc_info_val).__name__}: {str(exc_info_val)})"
            elif exc_info_val is True: # Indicates sys.exc_info() should be used by a real logger
                log_entry += " (Traceback requested)"
        
        # print(f"TEST_DEBUG_LOG: {log_entry}") # For live debugging of what's logged
        cls.log_messages.append(log_entry)

    DEFAULT_LOG_DIR = os.path.join(tempfile.gettempdir(), "logs_apply_git_diffs_test")

    @staticmethod
    def set_log_verbosity(level): pass
    @staticmethod
    def set_console_verbosity(level): pass
    @staticmethod
    def set_log_directory(path): pass
    @staticmethod
    def enable_file_logging(): pass

    @classmethod
    def clear_logs(cls):
        cls.log_messages = []

apply_git_diffs.debug_utils = DummyDebugUtils 

@pytest.fixture(autouse=True)
def clear_debug_logs_before_each_test():
    DummyDebugUtils.clear_logs()

# -----------------------
# Helper Function Tests
# -----------------------
def test_get_path_from_diff_header_line():
    assert get_path_from_diff_header_line("--- a/path/to/file.txt", "--- ") == "path/to/file.txt"
    assert get_path_from_diff_header_line("+++ b/another/file.py", "+++ ") == "another/file.py"
    assert get_path_from_diff_header_line("--- /dev/null", "--- ") == "dev/null"
    assert get_path_from_diff_header_line("--- a/.env", "--- ") == ".env"
    assert get_path_from_diff_header_line("--- a/no_ext_file", "--- ") == "no_ext_file"
    assert get_path_from_diff_header_line("--- file_no_prefix.txt", "--- ") == "file_no_prefix.txt"
    assert get_path_from_diff_header_line(None, "--- ") is None
    assert get_path_from_diff_header_line("--- a/b", "--- ") == "b"


# -----------------------
# Unit Tests for Core Logic (Using tmp_path: Path)
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
    assert hunks[0] == diff_lines # The whole input is one hunk's content

def test_extract_hunks_multiple():
    """Test extraction of multiple hunks."""
    diff_lines = [
        "@@ -1,2 +1,2 @@",
        " line1",
        "-old line2",
        "+new line2",
        "another line not part of hunk", # This should separate hunks
        "@@ -4,2 +4,2 @@",
        " line4",
        "-old line5",
        "+new line5",
    ]
    hunks = extract_hunks(diff_lines)
    assert len(hunks) == 2
    assert hunks[0] == ["@@ -1,2 +1,2 @@", " line1", "-old line2", "+new line2"]
    assert hunks[1] == ["@@ -4,2 +4,2 @@", " line4", "-old line5", "+new line5"]

def test_extract_hunks_with_no_newline_marker():
    diff_lines = [
        "@@ -1,1 +1,1 @@",
        "-old line",
        r"\ No newline at end of file",
        "+new line",
        r"\ No newline at end of file"
    ]
    hunks = extract_hunks(diff_lines)
    assert len(hunks) == 1
    assert hunks[0] == diff_lines
    assert len(hunks[0]) == 5

def test_apply_hunk_simple_replace(): # Was test_apply_hunk_simple
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
    """Test applying a hunk that includes context lines, deletion, and addition."""
    original_lines = ["a\n", "b\n", "c\n", "d\n"]
    hunk = [
        "@@ -2,2 +2,2 @@", # Original lines b, c
        " b",              # Context
        "-c",              # Deletion
        "+C_modified",     # Addition
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["a\n", "b\n", "C_modified\n", "d\n"]
    assert new_lines == expected

def test_apply_hunk_addition():
    original_lines = ["line1\n", "line3\n"]
    hunk_add_between = [
        "@@ -1,1 +1,2 @@",
        " line1",
        "+line2 added"
    ]
    new_lines = apply_hunk(original_lines, hunk_add_between)
    expected = ["line1\n", "line2 added\n", "line3\n"]
    assert new_lines == expected

def test_apply_hunk_deletion():
    original_lines = ["line1\n", "line2_to_delete\n", "line3\n"]
    hunk = [
        "@@ -1,3 +1,2 @@",
        " line1",
        "-line2_to_delete",
        " line3"
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["line1\n", "line3\n"]
    assert new_lines == expected

# --- Tests for '\ No newline at end of file' in apply_hunk ---
def test_apply_hunk_add_line_no_newline():
    original_lines = ["line1\n"]
    hunk = [
        "@@ -1,1 +1,2 @@",
        " line1",
        "+line2 no newline",
        r"\ No newline at end of file"
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["line1\n", "line2 no newline"]
    assert new_lines == expected

def test_apply_hunk_modify_to_no_newline():
    original_lines = ["line1\n", "line2 with newline\n"]
    hunk = [
        "@@ -2,1 +2,1 @@",
        "-line2 with newline",
        "+line2 modified no newline",
        r"\ No newline at end of file"
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["line1\n", "line2 modified no newline"]
    assert new_lines == expected

def test_apply_hunk_modify_from_no_newline_to_newline():
    original_lines = ["line1\n", "line2 no newline"]
    hunk = [
        "@@ -2,1 +2,1 @@",
        "-line2 no newline",
        r"\ No newline at end of file",
        "+line2 now with newline"
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["line1\n", "line2 now with newline\n"]
    assert new_lines == expected

def test_apply_hunk_context_no_newline_add_with_newline():
    original_lines = ["line1 no newline"]
    hunk = [
        "@@ -1,1 +1,2 @@",
        " line1 no newline",
        r"\ No newline at end of file",
        "+line2 with newline"
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["line1 no newline", "line2 with newline\n"]
    assert new_lines == expected

def test_apply_hunk_delete_line_with_no_newline_marker():
    original_lines = ["line1\n", "line2 no newline", "line3\n"]
    hunk = [
        "@@ -1,3 +1,2 @@", # Deleting line 2
        " line1",
        "-line2 no newline",
        r"\ No newline at end of file", # Marker for the deleted line
        " line3"
    ]
    new_lines = apply_hunk(original_lines, hunk)
    expected = ["line1\n", "line3\n"]
    assert new_lines == expected


def test_apply_unified_diff_no_hunks_returns_original(): # Was test_apply_unified_diff_no_hunks
    """Test applying a diff with no hunks returns original lines."""
    original_lines = ["a\n", "b\n", "c\n"]
    diff_content = "Some header info\nSome more header info\n" # No @@
    new_lines = apply_unified_diff(original_lines, diff_content)
    assert new_lines == original_lines
    assert id(new_lines) != id(original_lines) # Should be a copy

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

def test_apply_diff_to_file_new_file_creation(tmp_path: Path): # Was test_apply_diff_to_file_nonexistent, adapted
    """Test apply_diff_to_file for creating a new file."""
    file_path = tmp_path / "newly_created.txt"
    diff_content = (
        "--- /dev/null\n"  # Indicates a new file
        "+++ b/newly_created.txt\n"
        "@@ -0,0 +1,2 @@\n"
        "+first line\n"
        "+second line\n"
    )
    new_content_str = apply_diff_to_file(str(file_path), diff_content, False, str(file_path))
    expected_str = "first line\nsecond line\n"
    assert new_content_str == expected_str
    assert file_path.exists()
    assert file_path.read_text(encoding='utf-8') == expected_str

def test_apply_diff_to_file_creates_file_no_newline(tmp_path: Path): # New
    file_path = tmp_path / "new_no_newline.txt"
    diff_content = (
        "--- /dev/null\n"
        "+++ b/new_no_newline.txt\n"
        "@@ -0,0 +1,1 @@\n"
        "+content without newline\n"
        r"\ No newline at end of file"
    )
    new_content_str = apply_diff_to_file(str(file_path), diff_content, False, str(file_path))
    expected_str = "content without newline"
    assert new_content_str == expected_str
    assert file_path.read_text(encoding='utf-8') == expected_str


def test_apply_diff_to_file_existing(tmp_path: Path):
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
    new_content = apply_diff_to_file(str(file_path), diff_content, False, str(file_path))
    expected = "line1\nmodified line2\nline3\n"
    assert new_content == expected
    assert file_path.read_text(encoding='utf-8') == expected

def test_parse_diff_and_apply_valid_modification(tmp_path: Path): # was test_parse_diff_and_apply_valid
    """Test parse_diff_and_apply with a valid diff block for modification."""
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
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert file_rel_path in modified
    expected_content = "a\nB_modified\nc\n"
    assert modified[file_rel_path] == expected_content
    assert file_path.read_text(encoding='utf-8') == expected_content

def test_parse_diff_and_apply_existing_file_no_hunks_validation_fail(tmp_path: Path): # Replaces original test_parse_diff_and_apply_no_hunks
    """Test that modifying an existing file without hunks fails validation."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "test_no_hunks.txt"
    file_path = target_dir / file_rel_path
    original_content = "line1\nline2\n"
    file_path.write_text(original_content, encoding="utf-8")
    
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        # No '@@' hunks
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should fail validation and return empty dict"
    assert file_path.read_text(encoding="utf-8") == original_content # File unchanged
    assert any("Invalid diff block: No content hunks '@@' found for existing file modification" in msg for msg in DummyDebugUtils.log_messages)

def test_parse_and_apply_new_empty_file(tmp_path: Path): # New
    """Test creating a new empty file via a diff with no hunks or empty hunk."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    
    # Scenario 1: No hunks at all
    file_rel_path_no_hunks = "new_empty_no_hunks.txt"
    new_file_path_no_hunks = target_dir / file_rel_path_no_hunks
    diff_text_no_hunks = (
        f"diff --git a/{file_rel_path_no_hunks} b/{file_rel_path_no_hunks}\n"
        "new file mode 100644\n"
        "index 0000000..e69de29\n"
        f"--- /dev/null\n"
        f"+++ b/{file_rel_path_no_hunks}\n"
    )
    modified_no_hunks = parse_diff_and_apply(diff_text_no_hunks, str(target_dir), False, False)
    assert file_rel_path_no_hunks in modified_no_hunks
    assert modified_no_hunks[file_rel_path_no_hunks] == ""
    assert new_file_path_no_hunks.exists() and new_file_path_no_hunks.read_text(encoding='utf-8') == ""

    DummyDebugUtils.clear_logs() # Clear logs for next part of test

    # Scenario 2: With an empty hunk @@ -0,0 +0,0 @@
    file_rel_path_empty_hunk = "new_empty_empty_hunk.txt"
    new_file_path_empty_hunk = target_dir / file_rel_path_empty_hunk
    diff_text_empty_hunk = (
        f"diff --git a/{file_rel_path_empty_hunk} b/{file_rel_path_empty_hunk}\n"
        "new file mode 100644\n" # Often present for new files
        f"--- /dev/null\n"
        f"+++ b/{file_rel_path_empty_hunk}\n"
        "@@ -0,0 +0,0 @@\n"
    )
    modified_empty_hunk = parse_diff_and_apply(diff_text_empty_hunk, str(target_dir), False, False)
    assert file_rel_path_empty_hunk in modified_empty_hunk
    assert modified_empty_hunk[file_rel_path_empty_hunk] == ""
    assert new_file_path_empty_hunk.exists() and new_file_path_empty_hunk.read_text(encoding='utf-8') == ""


def test_parse_diff_and_apply_invalid_block_missing_file_markers(tmp_path: Path): # was test_parse_diff_and_apply_invalid_block
    """Test parse_diff_and_apply with an invalid diff block (missing file markers)."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    diff_text = (
        "diff --git a/missing.txt b/missing.txt\n" # This line is okay
        "Some invalid diff content without proper ---/+++ lines\n" # Problem here
        "@@ -1,1 +1,1 @@\n-a\n+b\n" # Hunks might be present but doesn't matter
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}
    assert any("Missing or unparsable '--- ' or '+++ '" in msg for msg in DummyDebugUtils.log_messages)

# -----------------------
# Tests for Main Functionality (main_testable)
# -----------------------

class MockTestArgs: # Renamed from MockArgs to avoid any potential global/local scope confusion if script structure changes
    def __init__(self, directory, input, log_level="Debug", console_log_level="Debug",
                 enable_file_log=False, log_dir="logs", force=False,
                 dry_run=False, output_copy=False):
        self.directory = directory
        self.input = input
        self.log_level = log_level
        self.console_log_level = console_log_level
        self.enable_file_log = enable_file_log
        self.log_dir = log_dir
        self.force = force
        self.dry_run = dry_run
        self.output_copy = output_copy


def test_main_testable_with_direct_diff(tmp_path: Path):
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
    args = MockTestArgs(directory=str(target_dir), input=diff_text)
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "new line\n"
    assert file_path.read_text(encoding="utf-8") == "new line\n"

def test_main_testable_no_diff_input(tmp_path: Path):
    """Test main_testable when no diff input is provided."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    args = MockTestArgs(directory=str(target_dir), input="")
    result = main_testable(args)
    assert "warning" in result
    assert result["warning"] == "No diff input provided."

def test_main_testable_from_file(tmp_path: Path):
    """Test main_testable when diff input is provided via a file."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "patch_target.txt" # Changed name to avoid conflict with diff file
    file_to_patch_path = target_dir / file_rel_path
    file_to_patch_path.write_text("original\n", encoding="utf-8")
    
    diff_input_file = tmp_path / "diff_source.txt" # Changed name
    diff_content = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-original\n"
        "+modified\n"
    )
    diff_input_file.write_text(diff_content, encoding="utf-8")
    args = MockTestArgs(directory=str(target_dir), input=str(diff_input_file))
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "modified\n"
    assert file_to_patch_path.read_text(encoding="utf-8") == "modified\n"

def test_main_testable_clipboard_fallback(monkeypatch, tmp_path: Path):
    """Test main_testable simulating clipboard input fallback to stdin."""
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
    def fake_clipboard_get_clipboard_empty(): # Simulate empty clipboard
        return ""

    monkeypatch.setattr(apply_git_diffs.clipboard, "get_clipboard", fake_clipboard_get_clipboard_empty)

    original_stdin = sys.stdin
    sys.stdin = io.StringIO(diff_text_for_stdin) # Stdin will provide the diff

    args = MockTestArgs(directory=str(target_dir), input="clipboard") # Request clipboard

    try:
        result = main_testable(args)
    finally:
        sys.stdin = original_stdin

    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "bar\n"
    assert file_path.read_text(encoding="utf-8") == "bar\n"
    # Corrected log message to match the code:
    assert any("Clipboard empty. Falling back to terminal." in msg for msg in DummyDebugUtils.log_messages)

def test_main_testable_new_empty_file(tmp_path: Path): # New
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "via_main_empty.txt"
    new_file_path = target_dir / file_rel_path
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- /dev/null\n"
        f"+++ b/{file_rel_path}\n"
        # No hunks
    )
    args = MockTestArgs(directory=str(target_dir), input=diff_text)
    result = main_testable(args)
    
    assert "modified_files" in result, f"Result was: {result}"
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == ""
    assert new_file_path.exists()
    assert new_file_path.read_text(encoding='utf-8') == ""

# -----------------------
# Additional Tests for Multiple Files / Edge Cases from Original
# -----------------------

def test_parse_and_apply_multiple_valid_diffs(tmp_path: Path):
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
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert file1_rel in modified and modified[file1_rel] == "Modified Line1A\nLine1B\n"
    assert file2_rel in modified and modified[file2_rel] == "Modified Line2A\nLine2B\n"
    assert file1_path.read_text(encoding='utf-8') == "Modified Line1A\nLine1B\n"
    assert file2_path.read_text(encoding='utf-8') == "Modified Line2A\nLine2B\n"


def test_parse_and_apply_multiple_with_one_invalid_diff_aborts_all(tmp_path: Path):
    target_dir = tmp_path
    file_rel = "file1.txt"
    file_path = target_dir / file_rel
    original_content = "Original\n"
    file_path.write_text(original_content, encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel} b/{file_rel}\n"
        f"--- a/{file_rel}\n"
        f"+++ b/{file_rel}\n"
        "@@ -1,1 +1,1 @@\n"
        "-Original\n"
        "+Modified\n"
        # Note: No extra newline here to ensure diff blocks are distinct
        f"diff --git a/invalid.txt b/invalid.txt\n" # Correctly starts new diff block
        f"--- a/invalid.txt\n" # Added for completeness
        f"+++ b/invalid.txt\n" # Added for completeness
        "Binary files a/invalid.txt and b/invalid.txt differ\n"
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should abort all if one diff block is unsupported"
    assert file_path.read_text(encoding="utf-8") == original_content
    assert any("Unsupported diff type: Binary file changes" in msg for msg in DummyDebugUtils.log_messages)

def test_parse_and_apply_diff_file_not_found_and_not_new_file_diff(tmp_path: Path):
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
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    
    assert file_rel_exists in modified
    assert modified[file_rel_exists] == "content modified\n"
    assert file_rel_nonexistent not in modified 
    assert not (target_dir / file_rel_nonexistent).exists()
    assert any(f"File '{target_dir / file_rel_nonexistent}' does not exist and not a new file diff" in msg for msg in DummyDebugUtils.log_messages)


# --- Tests for Multi-Hunk Scenarios ---
def test_apply_unified_diff_multiple_hunks_line_count_change():
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

def test_apply_diff_to_file_multiple_hunks_line_count_change(tmp_path: Path):
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
    new_content_str = apply_diff_to_file(str(file_path), diff_content, False, str(file_path))
    assert new_content_str == expected_content_str
    assert file_path.read_text(encoding='utf-8') == expected_content_str

# --- Tests for Unsupported Diff Types (should abort all) ---
def test_parse_and_apply_binary_file_diff_aborts_all(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    diff_text = (
        f"diff --git a/some_text_file.txt b/some_text_file.txt\n"
        f"--- a/some_text_file.txt\n"
        f"+++ b/some_text_file.txt\n"
        "@@ -0,0 +1,1 @@\n+hello\n" # A valid block first
        f"diff --git a/binary_file.dat b/binary_file.dat\n"
        f"--- a/binary_file.dat\n" # Added
        f"+++ b/binary_file.dat\n" # Added
        "Binary files a/binary_file.dat and b/binary_file.dat differ\n"
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should return empty dict for unsupported binary diff, aborting all"
    assert not (target_dir / "some_text_file.txt").exists() # First one should not be applied
    assert any("Unsupported diff type: Binary file changes" in msg for msg in DummyDebugUtils.log_messages)

def test_parse_and_apply_file_mode_change_only_diff_aborts_all(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / "script.sh").write_text("#!/bin/bash\necho hello\n", encoding="utf-8")
    diff_text = (
        f"diff --git a/script.sh b/script.sh\n"
        f"--- a/script.sh\n"  # Added
        f"+++ b/script.sh\n"  # Added
        "old mode 100644\n"
        "new mode 100755\n"
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should abort for mode-change-only diff"
    assert any("File mode change without content modification detected" in msg for msg in DummyDebugUtils.log_messages)

def test_parse_and_apply_symlink_diff_aborts_all(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    diff_text = (
        f"diff --git a/my_link b/my_link\n"
        f"--- /dev/null\n" # Symlink creation often has /dev/null for 'a'
        f"+++ b/my_link\n"
        "new file mode 120000\n" 
        "index 0000000..ea61be9\n" 
        "@@ -0,0 +1 @@\n+../target_file\n" 
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should abort for symlink diff"
    assert any("Symbolic link operation (mode 120000) detected" in msg for msg in DummyDebugUtils.log_messages)

def test_parse_and_apply_rename_diff_aborts_all(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    diff_text = (
        f"diff --git a/old_name.txt b/new_name.txt\n"
        f"--- a/old_name.txt\n" # Added
        f"+++ b/new_name.txt\n" # Added
        "rename from old_name.txt\n"
        "rename to new_name.txt\n"
        "similarity index 100%\n" # Common with renames
        # Optionally, hunks if content also changed, but rename itself is the issue
        "@@ -1,1 +1,1 @@\n-old content\n+new content\n"
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}, "Should abort for rename diff"
    assert any("File rename/copy operation detected" in msg for msg in DummyDebugUtils.log_messages)

# --- Tests for --dry-run and --output-copy ---
def test_dry_run_does_not_modify_file(tmp_path: Path):
    target_dir = tmp_path / "target"; target_dir.mkdir()
    file_rel_path = "dry_run_test.txt"; original_file_path = target_dir / file_rel_path
    original_content = "Original line 1\nOriginal line 2\n"; original_file_path.write_text(original_content, encoding="utf-8")
    diff_text = (f"diff --git a/{file_rel_path} b/{file_rel_path}\n--- a/{file_rel_path}\n+++ b/{file_rel_path}\n"
                 "@@ -1,2 +1,2 @@\n Original line 1\n-Original line 2\n+Modified line 2\n")
    args = MockTestArgs(directory=str(target_dir), input=diff_text, dry_run=True)
    result = main_testable(args)
    assert "modified_files" in result and result["modified_files"][file_rel_path] == "Original line 1\nModified line 2\n"
    assert original_file_path.read_text(encoding="utf-8") == original_content

def test_dry_run_new_file_not_created(tmp_path: Path):
    target_dir = tmp_path / "target"; target_dir.mkdir()
    file_rel_path = "new_dry_run_file.txt"; new_file_path = target_dir / file_rel_path
    diff_text = (f"diff --git a/{file_rel_path} b/{file_rel_path}\n--- /dev/null\n+++ b/{file_rel_path}\n"
                 "@@ -0,0 +1,1 @@\n+This is a new file.\n")
    args = MockTestArgs(directory=str(target_dir), input=diff_text, dry_run=True)
    result = main_testable(args)
    assert "modified_files" in result and result["modified_files"][file_rel_path] == "This is a new file.\n"
    assert not new_file_path.exists()

def test_output_copy_existing_file(tmp_path: Path):
    target_dir = tmp_path / "target"; target_dir.mkdir()
    file_rel_path = "output_copy_test.txt"; original_file_path = target_dir / file_rel_path
    original_content = "Line 1 original\nLine 2 to change\n"; original_file_path.write_text(original_content, encoding="utf-8")
    diff_text = (f"diff --git a/{file_rel_path} b/{file_rel_path}\n--- a/{file_rel_path}\n+++ b/{file_rel_path}\n"
                 "@@ -2,1 +2,1 @@\n-Line 2 to change\n+Line 2 MODIFIED\n")
    args = MockTestArgs(directory=str(target_dir), input=diff_text, output_copy=True)
    result = main_testable(args); expected_patched = "Line 1 original\nLine 2 MODIFIED\n"
    assert "modified_files" in result and result["modified_files"][file_rel_path] == expected_patched
    assert original_file_path.read_text(encoding="utf-8") == original_content
    name_part, ext_part = os.path.splitext(file_rel_path)
    copied_file_path = target_dir / f"{name_part}_applied_diff1{ext_part}"
    assert copied_file_path.exists() and copied_file_path.read_text(encoding="utf-8") == expected_patched

def test_output_copy_new_file(tmp_path: Path):
    target_dir = tmp_path / "target"; target_dir.mkdir()
    file_rel_path = "new_output_copy.txt"; original_path_if_not_copied = target_dir / file_rel_path
    diff_text = (f"diff --git a/{file_rel_path} b/{file_rel_path}\n--- /dev/null\n+++ b/{file_rel_path}\n"
                 "@@ -0,0 +1,2 @@\n+New file line 1.\n+New file line 2.\n")
    args = MockTestArgs(directory=str(target_dir), input=diff_text, output_copy=True)
    result = main_testable(args); expected_patched = "New file line 1.\nNew file line 2.\n"
    assert "modified_files" in result and result["modified_files"][file_rel_path] == expected_patched
    assert not original_path_if_not_copied.exists()
    name_part, ext_part = os.path.splitext(file_rel_path)
    copied_file_path = target_dir / f"{name_part}_applied_diff1{ext_part}"
    assert copied_file_path.exists() and copied_file_path.read_text(encoding="utf-8") == expected_patched

def test_output_copy_creates_sequential_names(tmp_path: Path):
    target_dir = tmp_path / "target"; target_dir.mkdir()
    file_rel_path = "sequential_test.txt"; original_file_path = target_dir / file_rel_path
    original_file_path.write_text("original", encoding="utf-8")
    name_part, ext_part = os.path.splitext(file_rel_path)
    (target_dir / f"{name_part}_applied_diff1{ext_part}").write_text("already here", encoding="utf-8")
    diff_text = (f"diff --git a/{file_rel_path} b/{file_rel_path}\n--- a/{file_rel_path}\n+++ b/{file_rel_path}\n"
                 "@@ -1,1 +1,1 @@\n-original\n+modified\n")
    args = MockTestArgs(directory=str(target_dir), input=diff_text, output_copy=True); main_testable(args)
    copied_file2_path = target_dir / f"{name_part}_applied_diff2{ext_part}"
    assert copied_file2_path.exists() and copied_file2_path.read_text(encoding="utf-8") == "modified\n"

def test_output_copy_existing_dotfile(tmp_path: Path):
    target_dir = tmp_path / "target"; target_dir.mkdir()
    file_rel_path = ".configfile"; original_file_path = target_dir / file_rel_path
    original_content = "key=value\n"; original_file_path.write_text(original_content, encoding="utf-8")
    diff_text = (f"diff --git a/{file_rel_path} b/{file_rel_path}\n--- a/{file_rel_path}\n+++ b/{file_rel_path}\n"
                 "@@ -1,1 +1,1 @@\n-key=value\n+key=new_value\n")
    args = MockTestArgs(directory=str(target_dir), input=diff_text, output_copy=True)
    result = main_testable(args); expected_patched = "key=new_value\n"
    assert file_rel_path in result["modified_files"] and result["modified_files"][file_rel_path] == expected_patched
    assert original_file_path.read_text(encoding="utf-8") == original_content
    copied_file_path = target_dir / f"{file_rel_path}_applied_diff1"
    assert copied_file_path.exists() and copied_file_path.read_text(encoding="utf-8") == expected_patched

# --- File Deletion Tests ---
def test_parse_and_apply_delete_file(tmp_path: Path):
    target_dir = tmp_path / "target"; target_dir.mkdir()
    file_rel_path = "to_delete.txt"; file_to_delete_path = target_dir / file_rel_path
    file_to_delete_path.write_text("line1\nline2\n", encoding="utf-8")
    diff_text = (f"diff --git a/{file_rel_path} b/{file_rel_path}\ndeleted file mode 100644\nindex d00491f..0000000\n"
                 f"--- a/{file_rel_path}\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-line1\n-line2\n")
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert file_rel_path in modified and modified[file_rel_path] == "DELETED" and not file_to_delete_path.exists()

def test_parse_and_apply_delete_file_dry_run(tmp_path: Path):
    target_dir = tmp_path / "target"; target_dir.mkdir()
    file_rel_path = "to_delete_dry.txt"; file_to_delete_path = target_dir / file_rel_path
    original_content = "content\n"; file_to_delete_path.write_text(original_content, encoding="utf-8")
    diff_text = (f"diff --git a/{file_rel_path} b/{file_rel_path}\n--- a/{file_rel_path}\n+++ /dev/null\n"
                 "@@ -1,1 +0,0 @@\n-content\n")
    modified = parse_diff_and_apply(diff_text, str(target_dir), True, False)
    assert file_rel_path in modified and modified[file_rel_path] == "WOULD_BE_DELETED"
    assert file_to_delete_path.exists() and file_to_delete_path.read_text(encoding="utf-8") == original_content

# -----------------------
# Edge Case Tests from Original
# -----------------------

def test_apply_hunk_invalid_header():
    original_lines = ["line1\n", "line2\n"]; hunk = ["INVALID HEADER", "-line2", "+new line2"]
    new_lines = apply_hunk(original_lines, hunk)
    assert new_lines == original_lines and id(new_lines) != id(original_lines)
    assert any("Malformed hunk header: INVALID HEADER" in msg for msg in DummyDebugUtils.log_messages)

def test_apply_diff_to_file_invalid_diff_content_no_hunks_for_existing_file(tmp_path: Path):
    file_path_obj = tmp_path / "invalid_diff_test.txt"
    original_file_content_str = "line1\nline2\n"; file_path_obj.write_text(original_file_content_str, encoding="utf-8")
    diff_content_invalid = (f"--- a/{file_path_obj.name}\n+++ b/{file_path_obj.name}\nNot a diff with hunks\n")
    result_content_str = apply_diff_to_file(str(file_path_obj), diff_content_invalid, False, str(file_path_obj))
    assert result_content_str == original_file_content_str
    assert file_path_obj.read_text(encoding="utf-8") == original_file_content_str
    assert any("No content hunks '@@' detected for existing file operation" in msg for msg in DummyDebugUtils.log_messages)

def test_apply_hunk_deletes_all_content_leaves_empty(tmp_path: Path):
    """Test a hunk that deletes all content from a file."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "all_deleted.txt"
    file_path = target_dir / file_rel_path
    file_path.write_text("line1\nline2\n", encoding="utf-8")

    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,2 +0,0 @@\n" # Delete 2 lines from line 1, add 0 lines
        "-line1\n"
        "-line2\n"
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert file_rel_path in modified
    assert modified[file_rel_path] == "" # Expect empty content
    assert file_path.read_text(encoding="utf-8") == ""

def test_apply_hunk_modifies_first_line(tmp_path: Path):
    """Test a hunk that modifies the very first line of a file."""
    original_lines = ["first line original\n", "second line\n"]
    hunk_data = [
        "@@ -1,1 +1,1 @@", # Modify 1 line starting at line 1
        "-first line original",
        "+first line modified"
    ]
    expected_lines = ["first line modified\n", "second line\n"]
    patched_lines = apply_git_diffs.apply_hunk(original_lines, hunk_data)
    assert patched_lines == expected_lines

def test_apply_hunk_modifies_last_line(tmp_path: Path):
    """Test a hunk that modifies the very last line of a file."""
    original_lines = ["first line\n", "last line original\n"]
    hunk_data = [
        "@@ -2,1 +2,1 @@", # Modify 1 line starting at line 2
        "-last line original",
        "+last line modified"
    ]
    expected_lines = ["first line\n", "last line modified\n"]
    patched_lines = apply_git_diffs.apply_hunk(original_lines, hunk_data)
    assert patched_lines == expected_lines

def test_apply_hunk_adds_newline_to_file_without_one(tmp_path: Path):
    """Test adding a newline to a file that previously ended without one."""
    original_lines = ["last line no newline"] # Original file content
    hunk_data = [
        "@@ -1,1 +1,1 @@",
        "-last line no newline",
        r"\ No newline at end of file",
        "+last line now with newline" # This implies it gets a newline by default
    ]
    # apply_hunk will add a newline to "+last line now with newline"
    expected_lines = ["last line now with newline\n"]
    patched_lines = apply_git_diffs.apply_hunk(original_lines, hunk_data)
    assert patched_lines == expected_lines

def test_apply_hunk_removes_newline_from_file_that_had_one(tmp_path: Path):
    """Test removing a newline from a file that previously ended with one."""
    original_lines = ["last line with newline\n"]
    hunk_data = [
        "@@ -1,1 +1,1 @@",
        "-last line with newline", # Original had a newline
        "+last line now no newline",
        r"\ No newline at end of file"
    ]
    expected_lines = ["last line now no newline"]
    patched_lines = apply_git_diffs.apply_hunk(original_lines, hunk_data)
    assert patched_lines == expected_lines

def test_apply_hunk_header_large_numbers_graceful_slicing(tmp_path: Path):
    """Test hunk with large line numbers that are out of bounds for original file."""
    original_lines = ["line1\n", "line2\n"]
    # This hunk implies changes far beyond the file's content.
    # Python slicing should handle this gracefully (empty slices).
    hunk_data = [
        "@@ -100,5 +100,5 @@", # Start deleting/adding at line 100
        "-old line far away1",
        "-old line far away2",
        "+new line far away1",
        "+new line far away2",
        "+new line far away3"
    ]
    # Expect no change as the hunk context is completely outside the file.
    # The current apply_hunk logic:
    # orig_slice_start_idx = 99, old_line_count = 5
    # prefix = original_lines[:99] -> will be all of original_lines
    # suffix = original_lines[99 + 5:] -> original_lines[104:] -> will be []
    # result = original_lines + new_hunk_lines_content + []
    # This would append the new lines. This is how patch might behave if it can't find context.
    # For a strict application like this script, if context doesn't match, it's an issue.
    # However, the provided hunk has no context lines, only additions/deletions.
    # A real `patch` might try to apply this at EOF or fail.
    # Our `apply_hunk` will effectively append if old_line_count is 0 for that section,
    # or replace/delete from an out-of-bounds index which results in no change to original for those parts.

    # Let's refine the test to be more about what our script *does*.
    # If old_start_line_num is > len(original_lines), old_line_count should effectively be 0 for deletion.
    # The current logic `suffix = original_lines[orig_slice_start_idx + old_line_count:]` handles this.
    
    patched_lines = apply_git_diffs.apply_hunk(original_lines, hunk_data)
    # Expected: original lines + new lines from hunk, as old lines are out of bounds.
    expected_lines = [
        "line1\n", "line2\n",
        "new line far away1\n", "new line far away2\n", "new line far away3\n"
    ]
    assert patched_lines == expected_lines

def test_parse_diff_and_apply_target_is_directory(tmp_path: Path):
    """Test when a diff targets a path that is actually a directory."""
    target_dir = tmp_path / "repo"
    target_dir.mkdir()

    file_rel_path = "a_file_or_dir"
    problematic_path_obj = target_dir / file_rel_path
    problematic_path_obj.mkdir() # Create a directory where the diff expects a file

    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n" 
        "-old\n"
        "+new\n"
    )
    DummyDebugUtils.clear_logs()
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    
    # This assertion should pass if the function correctly skips applying to a directory
    assert modified == {}, f"No modifications should be applied if target is a directory. Got: {modified}"

    # Check for the error log from apply_diff_to_file
    found_log = False
    expected_log_fragment_path = f"Error reading source file '{problematic_path_obj}'" # Use the Path object directly
    
    # Common error types/substrings when trying to open a directory as a file
    # IsADirectoryError is an OSError subclass.
    expected_error_substrings = ["IsADirectoryError", "Permission denied", "EISDIR", "[Errno 21] Is a directory"]


    for msg in DummyDebugUtils.log_messages:
        if expected_log_fragment_path in msg and "[Error]" in msg: # Ensure it's an error channel log
            # Check if any of the known error substrings are in the exception part of the message
            # This relies on the DummyDebugUtils appending the exception string if exc_info is passed.
            # Let's modify DummyDebugUtils to make this easier to check.
            # For now, let's assume the exception string `e` itself contains these.
            if any(err_sub in msg for err_sub in expected_error_substrings):
                found_log = True
                break
    
    if not found_log:
        print("\nCaptured logs for test_parse_diff_and_apply_target_is_directory:")
        for log_entry in DummyDebugUtils.log_messages:
            print(log_entry)
    
    assert found_log, "Should log an error (like IsADirectoryError or EISDIR) when trying to read a directory as a file"

def test_parse_diff_and_apply_mix_valid_and_skipped_non_new(tmp_path: Path):
    """Test a mix of a valid diff and a diff for a non-existent file (not new)."""
    target_dir = tmp_path / "ws"
    target_dir.mkdir()

    existing_file_rel = "existing.txt"
    existing_file_path = target_dir / existing_file_rel
    existing_file_path.write_text("line1\n", encoding="utf-8")

    non_existing_file_rel = "ghost.txt" # Does not exist, and diff is not for new file

    diff_text = (
        f"diff --git a/{existing_file_rel} b/{existing_file_rel}\n"
        f"--- a/{existing_file_rel}\n"
        f"+++ b/{existing_file_rel}\n"
        "@@ -1,1 +1,1 @@\n"
        "-line1\n"
        "+line one modified\n"
        f"diff --git a/{non_existing_file_rel} b/{non_existing_file_rel}\n"
        f"--- a/{non_existing_file_rel}\n" # Not /dev/null
        f"+++ b/{non_existing_file_rel}\n"
        "@@ -1,1 +1,1 @@\n"
        "-old ghost line\n"
        "+new ghost line\n"
    )
    DummyDebugUtils.clear_logs()
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)

    assert existing_file_rel in modified
    assert modified[existing_file_rel] == "line one modified\n"
    assert existing_file_path.read_text(encoding="utf-8") == "line one modified\n"

    assert non_existing_file_rel not in modified
    assert not (target_dir / non_existing_file_rel).exists()
    assert any(f"File '{target_dir / non_existing_file_rel}' does not exist and not a new file diff" in msg for msg in DummyDebugUtils.log_messages)


def test_output_copy_new_dotfile_no_ext(tmp_path: Path):
    """Test --output-copy for a new dotfile with no extension."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = ".newdotfile" # New dotfile, no extension
    
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- /dev/null\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -0,0 +1,1 @@\n"
        "+content for dotfile\n"
    )
    args = MockTestArgs(directory=str(target_dir), input=diff_text, dry_run=False, output_copy=True)
    result = main_testable(args)
    expected_patched_content = "content for dotfile\n"

    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == expected_patched_content
    
    # Original path (if not copied) should not exist
    original_path_if_not_copied = target_dir / file_rel_path
    assert not original_path_if_not_copied.exists()

    # Check for the copied file
    # get_output_copy_path logic: name_part=".newdotfile", ext_part=""
    # actual_name_for_suffix = ".newdotfile"
    expected_copy_filename = f"{file_rel_path}_applied_diff1" # .newdotfile_applied_diff1
    copied_file_path = target_dir / expected_copy_filename
    assert copied_file_path.exists(), f"Copied file '{copied_file_path}' should exist."
    assert copied_file_path.read_text(encoding="utf-8") == expected_patched_content

def test_apply_diff_to_file_new_empty_no_hunks(tmp_path: Path):
    """apply_diff_to_file should handle creation of an empty file when no hunks are provided."""
    file_path = tmp_path / "empty_created.txt"
    diff_content = (
        "--- /dev/null\n"
        "+++ b/empty_created.txt\n"
    )
    result = apply_diff_to_file(str(file_path), diff_content, False, str(file_path))
    assert result == ""
    assert file_path.exists() and file_path.read_text(encoding="utf-8") == ""

def test_parse_diff_and_apply_with_no_diff_blocks(tmp_path: Path):
    """parse_diff_and_apply should return empty dict when input lacks diff blocks."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    DummyDebugUtils.clear_logs()
    diff_text = "Random text with no diff blocks\n"
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}
    assert any("No 'diff --git' blocks found" in msg for msg in DummyDebugUtils.log_messages)

def test_parse_diff_and_apply_delete_nonexistent_file(tmp_path: Path):
    """Deletion diff for a non-existent file should be skipped with a warning."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "ghost.txt"
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-ghost\n"
    )
    DummyDebugUtils.clear_logs()
    modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
    assert modified == {}
    assert not (target_dir / file_rel_path).exists()
    assert any("File deletion specified for non-existent file" in msg for msg in DummyDebugUtils.log_messages)

def test_apply_hunk_ignores_unexpected_lines():
    """apply_hunk should ignore lines that do not start with expected diff markers."""
    original = ["line1\n"]
    hunk = [
        "@@ -1,1 +1,2 @@",
        " line1",
        "?unexpected stuff",
        "+line2",
    ]
    DummyDebugUtils.clear_logs()
    patched = apply_hunk(original, hunk)
    assert patched == ["line1\n", "line2\n"]
    assert any("Unexpected line in hunk body" in msg and "?unexpected stuff" in msg for msg in DummyDebugUtils.log_messages)

def test_diff_block_splitting_robustness(tmp_path: Path):
    """Test parsing of diff text with varying newlines between diff blocks."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file1_rel = "fileA.txt"
    file2_rel = "fileB.txt"
    (target_dir / file1_rel).write_text("original A\n", encoding="utf-8")
    (target_dir / file2_rel).write_text("original B\n", encoding="utf-8")

    # Test with no newline, one newline, and multiple newlines between blocks
    diff_texts = [
        ( # No newline
            f"diff --git a/{file1_rel} b/{file1_rel}\n--- a/{file1_rel}\n+++ b/{file1_rel}\n"
            "@@ -1,1 +1,1 @@\n-original A\n+modified A\n"
            f"diff --git a/{file2_rel} b/{file2_rel}\n--- a/{file2_rel}\n+++ b/{file2_rel}\n"
            "@@ -1,1 +1,1 @@\n-original B\n+modified B\n"
        ),
        ( # One newline
            f"diff --git a/{file1_rel} b/{file1_rel}\n--- a/{file1_rel}\n+++ b/{file1_rel}\n"
            "@@ -1,1 +1,1 @@\n-original A\n+modified A\n\n"
            f"diff --git a/{file2_rel} b/{file2_rel}\n--- a/{file2_rel}\n+++ b/{file2_rel}\n"
            "@@ -1,1 +1,1 @@\n-original B\n+modified B\n"
        ),
        ( # Multiple newlines
            f"diff --git a/{file1_rel} b/{file1_rel}\n--- a/{file1_rel}\n+++ b/{file1_rel}\n"
            "@@ -1,1 +1,1 @@\n-original A\n+modified A\n\n\n"
            f"diff --git a/{file2_rel} b/{file2_rel}\n--- a/{file2_rel}\n+++ b/{file2_rel}\n"
            "@@ -1,1 +1,1 @@\n-original B\n+modified B\n"
        ),
        ( # Text before first diff block
            "Some introductory text.\ndiff --git a/fileA.txt b/fileA.txt\n--- a/fileA.txt\n+++ b/fileA.txt\n"
            "@@ -1,1 +1,1 @@\n-original A\n+modified A\n"
            "diff --git a/fileB.txt b/fileB.txt\n--- a/fileB.txt\n+++ b/fileB.txt\n"
            "@@ -1,1 +1,1 @@\n-original B\n+modified B\n"
        )
    ]

    for i, diff_text in enumerate(diff_texts):
        # Reset file contents for each diff text variant
        (target_dir / file1_rel).write_text("original A\n", encoding="utf-8")
        (target_dir / file2_rel).write_text("original B\n", encoding="utf-8")
        DummyDebugUtils.clear_logs()

        modified = parse_diff_and_apply(diff_text, str(target_dir), False, False)
        
        assert file1_rel in modified, f"Test variant {i}: fileA.txt not modified. Logs: {DummyDebugUtils.log_messages}"
        assert modified[file1_rel] == "modified A\n", f"Test variant {i}: fileA.txt content mismatch"
        assert (target_dir / file1_rel).read_text(encoding="utf-8") == "modified A\n", f"Test variant {i}: fileA.txt disk content mismatch"

        assert file2_rel in modified, f"Test variant {i}: fileB.txt not modified. Logs: {DummyDebugUtils.log_messages}"
        assert modified[file2_rel] == "modified B\n", f"Test variant {i}: fileB.txt content mismatch"
        assert (target_dir / file2_rel).read_text(encoding="utf-8") == "modified B\n", f"Test variant {i}: fileB.txt disk content mismatch"

if __name__ == "__main__":
    pytest.main([__file__, "-s", "-v"])
# End of File: tests/apply_git_diffs_test.py
