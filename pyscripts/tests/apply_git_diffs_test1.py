import pytest
import os
import sys
from unittest import mock
import difflib
import io # Import io for StringIO

# Adjust sys.path to include the directory above the tests directory
# so that apply_git_diffs can be imported.
TESTS_DIR = os.path.dirname(__file__) # Directory where this test file is located
PARENT_DIR = os.path.dirname(TESTS_DIR) # Directory above the tests directory
sys.path.insert(0, PARENT_DIR) # Add the parent directory to sys.path

try:
    import apply_git_diffs
except ImportError:
    assert False, "Failed to import apply_git_diffs.py. Ensure it's in the directory above the tests directory."

# Now we can directly import clipboard_utils as it's installed
import clipboard_utils

try:
    import debug_utils
except ImportError:
    # Dummy debug_utils for testing when it's not available
    class debug_utils:
        @staticmethod
        def write_debug(message="", channel="Debug", condition=True, output_stream="stdout", location_channels=["Error", "Warning"]):
            if condition:
                print(f"[{channel}] {message}")


# --- Fixtures ---
@pytest.fixture
def test_directory(tmpdir):
    """Fixture to create a temporary directory for testing."""
    test_dir = tmpdir.mkdir("test_dir")
    return str(test_dir)

@pytest.fixture
def test_file(test_directory):
    """Fixture to create a test file in the test directory."""
    file_path = os.path.join(test_directory, "test_file.txt")
    with open(file_path, "w") as f:
        f.write("Original content line 1\nOriginal content line 2\n")
    return file_path

@pytest.fixture
def mock_clipboard_utils(monkeypatch):
    """Fixture to mock clipboard_utils.get_clipboard."""
    def mock_get_clipboard(return_value="clipboard content"):
        monkeypatch.setattr(clipboard_utils, 'get_clipboard', mock.Mock(return_value=return_value))

    def mock_get_clipboard_exception(exception=Exception("Clipboard error")):
        monkeypatch.setattr(clipboard_utils, 'get_clipboard', mock.Mock(side_effect=exception))

    return mock_get_clipboard, mock_get_clipboard_exception

@pytest.fixture
def mock_debug_write_debug(monkeypatch):
    """Fixture to mock debug_utils.write_debug and capture calls."""
    mock_write = mock.Mock()
    monkeypatch.setattr(debug_utils, 'write_debug', mock_write)
    return mock_write

# --- Tests for apply_diff_to_file function ---
class TestApplyDiffToFile:
    def test_apply_valid_diff(self, test_file, mock_debug_write_debug):
        diff_content = """--- a/test_file.txt
+++ b/test_file.txt
@@ -1,2 +2,2 @@
-Original content line 1
+Modified content line 1
 Original content line 2
"""
        apply_git_diffs.apply_diff_to_file(test_file, diff_content)
        with open(test_file, "r") as f:
            content = f.read()
        assert content == "Modified content line 1\nOriginal content line 2\n"
        mock_debug_write_debug.assert_any_call(f"Applying diff to file: {test_file}", channel="Information")
        mock_debug_write_debug.assert_any_call("Successfully applied diff to file: {}".format(test_file), channel="Information")

    def test_apply_diff_file_not_found(self, mock_debug_write_debug):
        filepath = "non_existent_file.txt"
        diff_content = "irrelevant diff content"
        result = apply_git_diffs.apply_diff_to_file(filepath, diff_content)
        assert not result
        mock_debug_write_debug.assert_any_call(f"File not found: {filepath}", channel="Error")

    def test_apply_diff_no_changes(self, test_file, mock_debug_write_debug):
        diff_content = """--- a/test_file.txt
+++ b/test_file.txt
""" # Empty diff
        result = apply_git_diffs.apply_diff_to_file(test_file, diff_content)
        assert result
        mock_debug_write_debug.assert_any_call(f"No changes detected for file: {test_file}", channel="Debug")

    def test_apply_diff_exception(self, test_file, mock_debug_write_debug, monkeypatch):
        def mock_file_open(*args, **kwargs):
            raise Exception("Mock file open error")
        monkeypatch.setattr("builtins.open", mock_file_open)

        diff_content = """--- a/test_file.txt
+++ b/test_file.txt
@@ -1,1 +1,1 @@
-Original content line 1
+Modified content line 1"""

        result = apply_git_diffs.apply_diff_to_file(test_file, diff_content)
        assert not result
        mock_debug_write_debug.assert_any_call(f"Error applying diff to file {test_file}: Mock file open error", channel="Error")

# --- Tests for parse_diff_and_apply function ---
class TestParseDiffAndApply:
    def test_parse_and_apply_single_diff(self, test_directory, mock_debug_write_debug):
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")
        diff_text = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        apply_git_diffs.parse_diff_and_apply(diff_text, test_directory)
        with open(file_path, "r") as f:
            content = f.read()
        assert content == "Modified content\n"
        mock_debug_write_debug.assert_any_call("Diff application process completed.", channel="Information")

    def test_parse_and_apply_multiple_diffs(self, test_directory, mock_debug_write_debug):
        file_path1 = os.path.join(test_directory, "file1.txt")
        file_path2 = os.path.join(test_directory, "file2.txt")
        with open(file_path1, "w") as f:
            f.write("Original content 1\n")
        with open(file_path2, "w") as f:
            f.write("Original content 2\n")
        diff_text = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content 1
+Modified content 1
diff --git a/file2.txt b/file2.txt
--- a/file2.txt
+++ b/file2.txt
@@ -1 +1,1 @@
-Original content 2
+Modified content 2
"""
        apply_git_diffs.parse_diff_and_apply(diff_text, test_directory)
        with open(file_path1, "r") as f:
            content1 = f.read()
        with open(file_path2, "r") as f:
            content2 = f.read()
        assert content1 == "Modified content 1\n"
        assert content2 == "Modified content 2\n"

    def test_parse_and_apply_invalid_diff_block_no_hunk(self, test_directory, mock_debug_write_debug):
        diff_text = """diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
No hunk here
"""
        apply_git_diffs.parse_diff_and_apply(diff_text, test_directory)
        mock_debug_write_debug.assert_any_call("Skipping diff block without hunks: file1.txt", channel="Warning")

    def test_parse_and_apply_invalid_diff_block_missing_ab_lines(self, test_directory, mock_debug_write_debug):
        diff_text = """diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        apply_git_diffs.parse_diff_and_apply(diff_text, test_directory)
        mock_debug_write_debug.assert_any_call("Skipping invalid diff block: Missing --- a/ or +++ b/\n{}".format("""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content"""), channel="Warning") # Corrected expected diff block in warning message

    def test_parse_and_apply_file_not_found_in_directory(self, test_directory, mock_debug_write_debug):
        diff_text = """diff --git a/non_existent_file.txt b/non_existent_file.txt
--- a/non_existent_file.txt
+++ b/non_existent_file.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        apply_git_diffs.parse_diff_and_apply(diff_text, test_directory)
        mock_debug_write_debug.assert_any_call("File '{}' not found in target directory, skipping diff application.".format(os.path.join(test_directory, 'non_existent_file.txt')), channel="Warning")

    def test_parse_and_apply_empty_diff_text(self, test_directory, mock_debug_write_debug):
        apply_git_diffs.parse_diff_and_apply("", test_directory)
        mock_debug_write_debug.assert_any_call("Diff application process completed.", channel="Information") # Expecting completion log even for empty diff

    def test_parse_and_apply_diff_block_processing_error(self, test_directory, mock_debug_write_debug, monkeypatch):
        def mock_apply_diff(*args, **kwargs):
            raise Exception("Error applying diff")
        monkeypatch.setattr(apply_git_diffs, 'apply_diff_to_file', mock_apply_diff)

        diff_text = """diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        apply_git_diffs.parse_diff_and_apply(diff_text, test_directory)
        mock_debug_write_debug.assert_any_call("Error processing diff block: Error applying diff\nBlock content:\n{}".format("""a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content"""), channel="Error")

# --- Tests for main function (integration tests) ---
class TestMainFunction:
    def test_main_apply_diff_from_clipboard(self, test_directory, mock_clipboard_utils, mock_debug_write_debug, monkeypatch):
        mock_get_clipboard, _ = mock_clipboard_utils
        mock_get_clipboard(return_value=f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
""")
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")

        monkeypatch.setattr(sys, 'argv', ['apply_git_diffs.py', '-d', test_directory])
        apply_git_diffs.main()

        with open(file_path, "r") as f:
            content = f.read()
        assert content == "Modified content\n"
        mock_debug_write_debug.assert_any_call("Reading diff from clipboard using clipboard_utils.", channel="Debug")
        mock_debug_write_debug.assert_any_call("Starting diff parsing and application.", channel="Information")

    def test_main_apply_diff_from_file(self, test_directory, mock_debug_write_debug, monkeypatch):
        diff_file_path = os.path.join(test_directory, "diff.txt")
        diff_content = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        with open(diff_file_path, "w") as f:
            f.write(diff_content)
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")

        monkeypatch.setattr(sys, 'argv', ['apply_git_diffs.py', '-d', test_directory, '-i', diff_file_path])
        apply_git_diffs.main()

        with open(file_path, "r") as f:
            content = f.read()
        assert content == "Modified content\n"
        mock_debug_write_debug.assert_any_call(f"Reading diff from file: {diff_file_path}", channel="Debug")
        mock_debug_write_debug.assert_any_call("Starting diff parsing and application.", channel="Information")

    def test_main_apply_diff_from_terminal_input(self, test_directory, mock_debug_write_debug, monkeypatch):
        diff_content = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")

        monkeypatch.setattr(sys, 'argv', ['apply_git_diffs.py', '-d', test_directory, '-i'])
        monkeypatch.setattr('sys.stdin', io.StringIO(diff_content)) # Mock stdin with diff content
        apply_git_diffs.main()

        with open(file_path, "r") as f:
            content = f.read()
        assert content == "Modified content\n"
        mock_debug_write_debug.assert_any_call("Reading diff from terminal input. Press Ctrl+D after pasting the diff.", channel="Debug")
        mock_debug_write_debug.assert_any_call("Starting diff parsing and application.", channel="Information")

    def test_main_invalid_directory(self, mock_debug_write_debug, monkeypatch):
        invalid_dir = "/path/that/does/not/exist"
        monkeypatch.setattr(sys, 'argv', ['apply_git_diffs.py', '-d', invalid_dir])
        apply_git_diffs.main()
        mock_debug_write_debug.assert_any_call(f"Error: Directory '{os.path.abspath(invalid_dir)}' does not exist.", channel="Error")

    def test_main_no_diff_input_clipboard_empty(self, test_directory, mock_clipboard_utils, mock_debug_write_debug, monkeypatch):
        mock_get_clipboard, _ = mock_clipboard_utils
        mock_get_clipboard(return_value="") # Empty clipboard
        monkeypatch.setattr('sys.stdin', io.StringIO("")) # Mock empty stdin *before* calling main

        monkeypatch.setattr(sys, 'argv', ['apply_git_diffs.py', '-d', test_directory])
        apply_git_diffs.main()
        mock_debug_write_debug.assert_any_call("No diff input provided.", channel="Warning")

    def test_main_no_diff_input_terminal_empty(self, test_directory, mock_debug_write_debug, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['apply_git_diffs.py', '-d', test_directory, '-i'])
        monkeypatch.setattr('sys.stdin', io.StringIO("")) # Mock empty stdin
        apply_git_diffs.main()
        mock_debug_write_debug.assert_any_call("No diff input provided.", channel="Warning")

    def test_main_clipboard_read_exception_fallback_terminal(self, test_directory, mock_clipboard_utils, mock_debug_write_debug, monkeypatch):
        _, mock_get_clipboard_exception = mock_clipboard_utils
        mock_get_clipboard_exception(exception=Exception("Clipboard read error"))

        diff_content = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        monkeypatch.setattr(sys, 'argv', ['apply_git_diffs.py', '-d', test_directory])
        monkeypatch.setattr('sys.stdin', io.StringIO(diff_content)) # Provide diff via stdin as fallback
        apply_git_diffs.main()

        mock_debug_write_debug.assert_any_call("Error reading from clipboard using clipboard_utils: Exception('Clipboard read error'). Falling back to terminal input.", channel="Warning")
        mock_debug_write_debug.assert_any_call("Reading diff from terminal input. Press Ctrl+D after pasting the diff.", channel="Debug")
        mock_debug_write_debug.assert_any_call("Starting diff parsing and application.", channel="Information")

    def test_main_direct_input_as_diff_text(self, test_directory, mock_debug_write_debug, monkeypatch):
        diff_text_arg = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")

        monkeypatch.setattr(sys, 'argv', ['apply_git_diffs.py', '-d', test_directory, '-i', diff_text_arg]) # -i with direct diff text
        apply_git_diffs.main()

        with open(file_path, "r") as f:
            content = f.read()
        assert content == "Modified content\n"
        mock_debug_write_debug.assert_any_call("Treating input as direct diff text.", channel="Debug")
        mock_debug_write_debug.assert_any_call("Starting diff parsing and application.", channel="Information")
