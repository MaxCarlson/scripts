import pytest
import os
import sys
import difflib
import io
from unittest import mock
import tempfile

# Add current directory to sys.path to import apply_git_diffs
sys.path.insert(0, '.')

# Import your apply_git_diffs script
import apply_git_diffs  # Assuming your script is named apply_git_diffs.py


class TestApplyGitDiffsInMemoryPytest:  # Test class for in-memory tests

    def test_apply_valid_diff(self): # Test 1 (Pytest)
        test_directory = "test_dir"
        os.makedirs(test_directory, exist_ok=True)
        test_file_path = os.path.join(test_directory, "test_file.txt")
        original_content = "Original content line 1\nOriginal content line 2\n"

        diff_content = """--- a/test_file.txt
+++ b/test_file.txt
@@ -1,2 +2,2 @@
-Original content line 1
+Modified content line 1
 Original content line 2
"""
        updated_content = apply_git_diffs.apply_diff_to_file(test_file_path, diff_content)
        expected_content = "Modified content line 1\nOriginal content line 2\n"
        assert updated_content == expected_content

    def test_apply_diff_file_not_found(self): # Test 2 (Pytest)
        filepath = "non_existent_file.txt"
        diff_content = "irrelevant diff content"
        updated_content = apply_git_diffs.apply_diff_to_file(filepath, diff_content)
        assert updated_content is None

    def test_apply_diff_no_changes(self): # Test 3 (Pytest)
        test_directory = "test_dir"
        os.makedirs(test_directory, exist_ok=True)
        test_file_path = os.path.join(test_directory, "test_file.txt")
        original_content = "Original content line 1\nOriginal content line 2\n"
        with open(test_file_path, "w") as f:
            f.write(original_content)

        diff_content = """--- a/test_file.txt
+++ b/test_file.txt
"""
        updated_content = apply_git_diffs.apply_diff_to_file(test_file_path, diff_content)
        assert updated_content == ""

    def test_parse_and_apply_single_diff(self): # Test 4 (Pytest)
        test_directory = "test_dir_4"
        os.makedirs(test_directory, exist_ok=True)
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
        modified_contents = apply_git_diff_s.parse_diff_and_apply(diff_text, test_directory) # Corrected function name
        actual_content = modified_contents.get("file1.txt", "")
        expected_content = "Modified content\n"
        assert actual_content == expected_content

    def test_parse_and_apply_multiple_diffs(self): # Test 5 (Pytest)
        test_directory = "test_dir_5"
        os.makedirs(test_directory, exist_ok=True)
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
        modified_contents = apply_git_diff_s.parse_diff_and_apply(diff_text, test_directory) # Corrected function name
        content1 = modified_contents.get("file1.txt", "")
        content2 = modified_contents.get("file2.txt", "")
        expected_content1 = "Modified content 1\n"
        expected_content2 = "Modified content 2\n"
        assert content1 == expected_content1
        assert content2 == expected_content2

    def test_parse_and_apply_invalid_diff_block_no_hunk(self): # Test 6 (Pytest)
        test_directory = "test_dir_6"
        os.makedirs(test_directory, exist_ok=True)
        diff_text = """diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
No hunk here
"""
        modified_contents = apply_git_diff_s.parse_diff_and_apply(diff_text, test_directory) # Corrected function name
        assert not modified_contents

    def test_parse_and_apply_invalid_diff_block_missing_ab_lines(self): # Test 7 (Pytest)
        test_directory = "test_dir_7"
        os.makedirs(test_directory, exist_ok=True)
        diff_text = """diff --git a/file1.txt b/file1.txt
Missing a/b lines but has hunk
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        modified_contents = apply_git_diff_s.parse_diff_and_apply(diff_text, test_directory) # Corrected function name
        assert not modified_contents

    def test_parse_and_apply_file_not_found_in_directory(self): # Test 8 (Pytest)
        test_directory = "test_dir_8"
        os.makedirs(test_directory, exist_ok=True)
        diff_text = """diff --git a/non_existent_file.txt b/non_existent_file.txt
--- a/non_existent_file.txt
+++ b/non_existent_file.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        modified_contents = apply_git_diff_s.parse_diff_and_apply(diff_text, test_directory) # Corrected function name
        assert not modified_contents

    def test_main_apply_diff_from_clipboard(self, monkeypatch): # Test 9 (Pytest)
        test_directory = "test_dir_9"
        os.makedirs(test_directory, exist_ok=True)
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
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source='clipboard') # Use wrapper
        actual_content = main_output['modified_files'].get("file1.txt", "")
        expected_content = "Modified content\n"
        assert actual_content == expected_content
        assert main_output["input_source"] == "clipboard"

    def test_main_apply_diff_from_file(self, monkeypatch): # Test 10 (Pytest)
        test_directory = "test_dir_10"
        os.makedirs(test_directory, exist_ok=True)
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")
        diff_file_path = os.path.join(test_directory, "diff.txt") # Dummy diff file path
        diff_content = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        with open(diff_file_path, "w") as f: # Create dummy diff file
            f.write(diff_content)
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory, '-i', diff_file_path])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source='file')
        actual_content = main_output['modified_files'].get("file1.txt", "")
        expected_content = "Modified content\n"
        assert actual_content == expected_content
        assert main_output["input_source"] == 'file'

    def test_main_apply_diff_from_terminal_input(self, monkeypatch): # Test 11 (Pytest)
        test_directory = "test_dir_11"
        os.makedirs(test_directory, exist_ok=True)
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")
        diff_content = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory, '-i'])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source='terminal_input', diff_text_terminal=diff_content) # Pass diff_text
        actual_content = main_output['modified_files'].get("file1.txt", "")
        expected_content = "Modified content\n"
        assert actual_content == expected_content
        assert main_output["input_source"] == 'terminal_input'

    def test_main_invalid_directory(self, monkeypatch): # Test 12 (Pytest)
        invalid_dir = "/path/that/does/not/exist"
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', invalid_dir])
        main_output = apply_git_diffs.main_test_wrapper(invalid_dir, input_source='clipboard')
        assert "error" in main_output
        assert "Directory" in main_output["error"]
        assert "does not exist" in main_output["error"]

    def test_main_no_diff_input_clipboard_empty(self, monkeypatch): # Test 13 (Pytest)
        test_directory = "test_dir_13"
        os.makedirs(test_directory, exist_ok=True)
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source='clipboard')
        assert "warning" in main_output
        assert main_output["warning"] == "No diff input provided."

    def test_main_no_diff_input_terminal_empty(self, monkeypatch): # Test 14 (Pytest)
        test_directory = "test_dir_14"
        os.makedirs(test_directory, exist_ok=True)
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory, '-i'])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source='terminal_input', diff_text_terminal="")
        assert "warning" in main_output
        assert main_output["warning"] == "No diff input provided."

    def test_main_clipboard_read_exception_fallback_terminal(self, monkeypatch): # Test 15 (Pytest)
        test_directory = "test_dir_15"
        os.makedirs(test_directory, exist_ok=True)
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")
        diff_content = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source='clipboard', diff_text_terminal=diff_content)
        actual_content = main_output['modified_files'].get("file1.txt", "")
        expected_content = "Modified content\n"
        assert actual_content == expected_content
        assert main_output["input_source"] == 'terminal_input' # Check fallback

    def test_main_direct_input_as_diff_text(self, monkeypatch): # Test 16 (Pytest)
        test_directory = "test_dir_16"
        os.makedirs(test_directory, exist_ok=True)
        file_path = os.path.join(test_directory, "file1.txt")
        with open(file_path, "w") as f:
            f.write("Original content\n")
        diff_text_arg = f"""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1 +1,1 @@
-Original content
+Modified content
"""
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory, '-i', diff_text_arg])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source=diff_text_arg)
        actual_content = main_output['modified_files'].get("file1.txt", "")
        expected_content = "Modified content\n"
        assert actual_content == expected_content
        assert main_output["input_source"] == diff_text_arg # Check direct input

    def test_main_no_diff_input_clipboard_empty_terminal_empty(self, monkeypatch): # Test 17 (Pytest)
        test_directory = "test_dir_17"
        os.makedirs(test_directory, exist_ok=True)
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory, '-i'])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source='clipboard', diff_text_terminal="")
        assert "warning" in main_output
        assert main_output["warning"] == "No diff input provided."

    def test_main_file_input_error(self, monkeypatch): # Test 18 (Pytest)
        test_directory = "test_dir_18"
        os.makedirs(test_directory, exist_ok=True)
        invalid_file_path = "/path/to/non_existent_diff_file.txt"
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', test_directory, '-i', invalid_file_path])
        main_output = apply_git_diffs.main_test_wrapper(test_directory, input_source='file')
        assert "error" in main_output
        assert "Error reading from file" in main_output["error"]

    def test_main_no_directory_provided(self, monkeypatch): # Test 19 (Pytest)
        monkeypatch.setattr('sys.argv', ['apply_git_diffs.py', '-d', None]) # Simulate no directory
        main_output = apply_git_diffs.main_test_wrapper(directory=None, input_source='clipboard')
        assert "error" in main_output
        assert "Error: Directory" in main_output["error"]
        assert "does not exist." in main_output["error"]