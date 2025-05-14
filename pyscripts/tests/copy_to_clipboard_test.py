import sys
import pytest
from pathlib import Path
from unittest import mock # Python's built-in mock library

# --- Pre-emptive Mocking of the clipboard utility module ---
# This ensures that when 'copy_to_clipboard' (your script) is imported,
# it finds a mock for 'cross_platform.clipboard_utils' and doesn't try to exit
# due to a real ImportError if the utils were somehow not truly found by the test runner's env,
# or to ensure we are using our controlled mocks.
MOCK_CLIPBOARD_MODULE_NAME = 'cross_platform.clipboard_utils'
mock_utils_module = mock.MagicMock()

# Set up the mock functions that your script imports from the mocked module
mock_utils_module.set_clipboard = mock.MagicMock()
mock_utils_module.get_clipboard = mock.MagicMock(return_value="") # Default good return for validation

sys.modules[MOCK_CLIPBOARD_MODULE_NAME] = mock_utils_module
# --- End of Pre-emptive Mocking ---

# Now it's safe to import your script's functions.
# Ensure copy_to_clipboard.py is in a location where Python can find it
# (e.g., same directory, parent directory if pytest is run from there, or in PYTHONPATH)
import copy_to_clipboard # <--- CORRECTED: Use your actual script name

# Helper function to create dummy files for tests
def create_dummy_file(tmp_path: Path, filename: str, content: str = "") -> Path:
    file = tmp_path / filename
    file.write_text(content, encoding="utf-8")
    return file

# --- Test Cases ---

def test_single_file_raw_copy(tmp_path: Path, mocker, capsys):
    """Test copying a single file results in raw content being set to clipboard."""
    # Patch the set_clipboard and get_clipboard functions *as they are used by copy_to_clipboard.py*
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    file_content = "Hello, World!\nThis is a single file."
    single_file_path = create_dummy_file(tmp_path, "single.txt", file_content)

    mock_get_clipboard.return_value = file_content # Simulate perfect clipboard behavior for validation

    # Call the function from your script
    copy_to_clipboard.copy_files_to_clipboard([str(single_file_path)])

    mock_set_clipboard.assert_called_once_with(file_content)
    mock_get_clipboard.assert_called_once() # Ensure validation was attempted

    captured = capsys.readouterr()
    assert f"[INFO] Successfully read '{single_file_path}'." in captured.out # Adjusted to match actual script output
    assert f"raw content from 1 file ('{single_file_path}') (2 lines total)" in captured.out
    assert "[SUCCESS] Clipboard copy complete and content verified." in captured.out

def test_single_empty_file_raw_copy(tmp_path: Path, mocker, capsys):
    """Test copying a single empty file."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    empty_file_path = create_dummy_file(tmp_path, "empty.txt", "")
    mock_get_clipboard.return_value = "" # Empty string from clipboard

    copy_to_clipboard.copy_files_to_clipboard([str(empty_file_path)])

    mock_set_clipboard.assert_called_once_with("")
    mock_get_clipboard.assert_called_once()

    captured = capsys.readouterr()
    assert f"[INFO] Successfully read '{empty_file_path}'." in captured.out # Adjusted
    assert f"raw content from 1 file ('{empty_file_path}') (0 lines total)" in captured.out
    assert "[SUCCESS] Clipboard copy complete and content verified." in captured.out

def test_single_file_not_found(tmp_path: Path, mocker, capsys):
    """Test behavior when a single specified file is not found."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    # get_clipboard should not be called if the script returns early

    non_existent_file = tmp_path / "notfound.txt"

    copy_to_clipboard.copy_files_to_clipboard([str(non_existent_file)])

    mock_set_clipboard.assert_not_called()

    captured = capsys.readouterr()
    assert f"[ERROR] File not found: '{non_existent_file}'. Nothing will be copied." in captured.out

def test_multiple_files_formatted_copy(tmp_path: Path, mocker, capsys):
    """Test copying multiple files results in formatted content."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    file1_content = "Content of file1."
    file2_content = "Content of file2.\nThis has two lines."
    file1_path = create_dummy_file(tmp_path, "file1.txt", file1_content)
    file2_path = create_dummy_file(tmp_path, "file2.txt", file2_content)

    separator_visual = "---" * 18
    header1 = f"{separator_visual}\n--- Start of file: {file1_path} ---\n{separator_visual}"
    footer1 = f"{separator_visual}\n--- End of file: {file1_path} ---\n{separator_visual}"
    block1 = f"{header1}\n{file1_content}\n{footer1}"

    header2 = f"{separator_visual}\n--- Start of file: {file2_path} ---\n{separator_visual}"
    footer2 = f"{separator_visual}\n--- End of file: {file2_path} ---\n{separator_visual}"
    block2 = f"{header2}\n{file2_content}\n{footer2}"

    expected_clipboard_content = f"{block1}\n\n{block2}"
    mock_get_clipboard.return_value = expected_clipboard_content

    copy_to_clipboard.copy_files_to_clipboard([str(file1_path), str(file2_path)])

    mock_set_clipboard.assert_called_once_with(expected_clipboard_content)
    mock_get_clipboard.assert_called_once()

    captured = capsys.readouterr()
    assert f"[INFO] Successfully processed '{file1_path}' for aggregation." in captured.out
    assert f"[INFO] Successfully processed '{file2_path}' for aggregation." in captured.out
    expected_lines_count = len(expected_clipboard_content.splitlines())
    assert f"formatted content from 2 of 2 specified file(s) ({expected_lines_count} lines total)" in captured.out
    assert "[SUCCESS] Clipboard copy complete and content verified." in captured.out

def test_multiple_files_one_not_found(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    file1_content = "Existing file content."
    file1_path = create_dummy_file(tmp_path, "exists.txt", file1_content)
    non_existent_file = tmp_path / "notfound.txt"

    separator_visual = "---" * 18
    header1 = f"{separator_visual}\n--- Start of file: {file1_path} ---\n{separator_visual}"
    footer1 = f"{separator_visual}\n--- End of file: {file1_path} ---\n{separator_visual}"
    expected_clipboard_content = f"{header1}\n{file1_content}\n{footer1}"
    mock_get_clipboard.return_value = expected_clipboard_content

    copy_to_clipboard.copy_files_to_clipboard([str(file1_path), str(non_existent_file)])

    mock_set_clipboard.assert_called_once_with(expected_clipboard_content)
    mock_get_clipboard.assert_called_once()

    captured = capsys.readouterr()
    assert f"[INFO] Successfully processed '{file1_path}' for aggregation." in captured.out
    assert f"[WARNING] File not found: '{non_existent_file}'. Skipping this file." in captured.out
    expected_lines_count = len(expected_clipboard_content.splitlines())
    assert f"formatted content from 1 of 2 specified file(s) ({expected_lines_count} lines total)" in captured.out
    assert "[SUCCESS] Clipboard copy complete and content verified." in captured.out

def test_multiple_files_all_not_found(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')

    non_existent1 = tmp_path / "notfound1.txt"
    non_existent2 = tmp_path / "notfound2.txt"

    copy_to_clipboard.copy_files_to_clipboard([str(non_existent1), str(non_existent2)])

    mock_set_clipboard.assert_not_called()

    captured = capsys.readouterr()
    assert f"[WARNING] File not found: '{non_existent1}'. Skipping this file." in captured.out
    assert f"[WARNING] File not found: '{non_existent2}'. Skipping this file." in captured.out
    assert "[INFO] No content was successfully processed from any of the multiple files. Clipboard not updated." in captured.out

def test_validation_logic_truncated_clipboard(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    file_content = "Line 1\nLine 2\nLine 3 is very long."
    single_file_path = create_dummy_file(tmp_path, "full.txt", file_content)
    truncated_content = "Line 1\nLine 2"
    mock_get_clipboard.return_value = truncated_content

    copy_to_clipboard.copy_files_to_clipboard([str(single_file_path)])

    mock_set_clipboard.assert_called_once_with(file_content)
    mock_get_clipboard.assert_called_once()

    captured = capsys.readouterr()
    assert "[WARNING] Clipboard content may be truncated or incomplete: 2 lines found in clipboard vs. 3 expected." in captured.out

def test_set_clipboard_not_implemented(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard', side_effect=NotImplementedError("set_clipboard NI"))
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard') # Won't be called

    file_content = "Some content."
    single_file_path = create_dummy_file(tmp_path, "test.txt", file_content)

    copy_to_clipboard.copy_files_to_clipboard([str(single_file_path)])

    mock_set_clipboard.assert_called_once_with(file_content)
    mock_get_clipboard.assert_not_called()

    captured = capsys.readouterr()
    assert "[ERROR] set_clipboard is not implemented in clipboard_utils. Cannot copy content." in captured.out

def test_get_clipboard_not_implemented(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard', side_effect=NotImplementedError("get_clipboard NI"))

    file_content = "Validation content."
    single_file_path = create_dummy_file(tmp_path, "validate.txt", file_content)

    copy_to_clipboard.copy_files_to_clipboard([str(single_file_path)])

    mock_set_clipboard.assert_called_once_with(file_content)
    mock_get_clipboard.assert_called_once()

    captured = capsys.readouterr()
    assert "[INFO] get_clipboard is not implemented in clipboard_utils. Skipping verification step." in captured.out
