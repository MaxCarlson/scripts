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
        "@@ -0,0 +1,2 @@\n"
        "+first line\n"
        "+second line\n"
    )
    new_content = apply_diff_to_file(str(file_path), diff_content)
    assert new_content == "first line\nsecond line\n"
    # Verify file exists with expected content.
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert content == "first line\nsecond line\n"

def test_apply_diff_to_file_existing(tmp_path):
    """Test applying a diff to an existing file."""
    file_path = tmp_path / "file.txt"
    original_content = "line1\nline2\nline3\n"
    file_path.write_text(original_content, encoding='utf-8')
    diff_content = (
        "@@ -2,1 +2,1 @@\n"
        "-line2\n"
        "+modified line2\n"
    )
    new_content = apply_diff_to_file(str(file_path), diff_content)
    expected = "line1\nmodified line2\nline3\n"
    assert new_content == expected
    # Verify on-disk content.
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
    modified = parse_diff_and_apply(diff_text, str(target_dir))
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
        "Some header text\n"
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir))
    assert modified == {}

def test_parse_diff_and_apply_invalid_block(tmp_path):
    """Test parse_diff_and_apply with an invalid diff block (missing file markers)."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    diff_text = (
        "diff --git a/missing.txt b/missing.txt\n"
        "Some invalid diff content without proper ---/+++ lines\n"
    )
    modified = parse_diff_and_apply(diff_text, str(target_dir))
    assert modified == {}

# -----------------------
# Tests for Main Functionality (main_testable)
# -----------------------

class MockArgs:
    def __init__(self, directory, input, log_level="Debug", console_log_level="Debug", enable_file_log=False, log_dir="logs"):
        self.directory = directory
        self.input = input
        self.log_level = log_level
        self.console_log_level = console_log_level
        self.enable_file_log = enable_file_log
        self.log_dir = log_dir

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
    args = MockArgs(directory=str(target_dir), input=diff_text)
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "new line\n"
    assert file_path.read_text(encoding="utf-8") == "new line\n"

def test_main_testable_no_diff_input(monkeypatch, tmp_path):
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
    file_path = target_dir / file_rel_path
    file_path.write_text("original\n", encoding="utf-8")
    diff_file = tmp_path / "diff.txt"
    diff_content = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-original\n"
        "+modified\n"
    )
    diff_file.write_text(diff_content, encoding="utf-8")
    args = MockArgs(directory=str(target_dir), input=str(diff_file))
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "modified\n"
    assert file_path.read_text(encoding="utf-8") == "modified\n"

def test_main_testable_clipboard_fallback(monkeypatch, tmp_path):
    """Test main_testable simulating clipboard input fallback.
    
    Monkey-patch clipboard.get_clipboard to raise an exception so that
    the code falls back to reading from sys.stdin.
    """
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    file_rel_path = "file.txt"
    file_path = target_dir / file_rel_path
    file_path.write_text("foo\n", encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel_path} b/{file_rel_path}\n"
        f"--- a/{file_rel_path}\n"
        f"+++ b/{file_rel_path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-foo\n"
        "+bar\n"
    )
    def fake_clipboard_get_clipboard():
        raise Exception("Clipboard error")
    monkeypatch.setattr(apply_git_diffs.clipboard, "get_clipboard", fake_clipboard_get_clipboard)
    monkeypatch.setattr(sys, "stdin", io.StringIO(diff_text))
    args = MockArgs(directory=str(target_dir), input="clipboard")
    result = main_testable(args)
    assert "modified_files" in result
    assert file_rel_path in result["modified_files"]
    assert result["modified_files"][file_rel_path] == "bar\n"
    assert file_path.read_text(encoding="utf-8") == "bar\n"

# -----------------------
# Additional Tests for New Scenarios
# -----------------------

def test_parse_and_apply_multiple_valid_diffs(tmp_path):
    """
    Test applying a diff text that contains multiple valid diff blocks.
    Expect that all diffs are applied.
    """
    file1_rel = "file1.txt"
    file2_rel = "file2.txt"
    file1_path = tmp_path / file1_rel
    file2_path = tmp_path / file2_rel
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
    modified = parse_diff_and_apply(diff_text, str(tmp_path))
    assert file1_rel in modified
    assert file2_rel in modified
    assert modified[file1_rel] == "Modified Line1A\nLine1B\n"
    assert modified[file2_rel] == "Modified Line2A\nLine2B\n"

def test_parse_and_apply_multiple_with_invalid_diff(tmp_path):
    """
    Test that if multiple diff blocks are passed and one is invalid,
    then no diffs should be applied (transactional behavior).
    """
    file_rel = "file1.txt"
    file_path = tmp_path / file_rel
    file_path.write_text("Original\n", encoding="utf-8")
    diff_text = (
        f"diff --git a/{file_rel} b/{file_rel}\n"
        f"--- a/{file_rel}\n"
        f"+++ b/{file_rel}\n"
        "@@ -1 +1,1 @@\n"
        "-Original\n"
        "+Modified\n"
        "\n"
        "diff --git a/invalid.txt b/invalid.txt\n"
        "Some random text that does not conform to diff format\n"
        "@@ -1 +1,1 @@\n"
        "-Foo\n"
        "+Bar\n"
    )
    modified = parse_diff_and_apply(diff_text, str(tmp_path))
    assert modified == {}
    assert file_path.read_text(encoding="utf-8") == "Original\n"

def test_parse_and_apply_diff_file_not_found(tmp_path):
    """
    Test that if a diff block targets a file not present in the target directory,
    then no diff is applied.
    """
    file_rel = "nonexistent.txt"
    diff_text = (
        f"diff --git a/{file_rel} b/{file_rel}\n"
        f"--- a/{file_rel}\n"
        f"+++ b/{file_rel}\n"
        "@@ -1,1 +1,1 @@\n"
        "-Some content\n"
        "+Modified content\n"
    )
    modified = parse_diff_and_apply(diff_text, str(tmp_path))
    assert modified == {}

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

def test_apply_diff_to_file_invalid_diff():
    """Test apply_diff_to_file with diff input that does not contain hunks."""
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8") as tf:
        tf.write("line1\nline2\n")
        tf.flush()
        filename = tf.name
    try:
        diff_content = "Not a diff\nNo hunk info here\n"
        result = apply_diff_to_file(filename, diff_content)
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        assert content == "line1\nline2\n"
        assert result == "line1\nline2\n"
    finally:
        os.remove(filename)

if __name__ == "__main__":
    pytest.main()

