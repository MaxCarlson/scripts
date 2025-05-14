import sys
import os
import pytest
from pathlib import Path
from unittest import mock # Python's built-in mock library

# --- Pre-emptive Mocking of the clipboard utility module ---
MOCK_CLIPBOARD_MODULE_NAME = 'cross_platform.clipboard_utils'
mock_utils_module = mock.MagicMock()

mock_utils_module.set_clipboard = mock.MagicMock()
mock_utils_module.get_clipboard = mock.MagicMock(return_value="") 

sys.modules[MOCK_CLIPBOARD_MODULE_NAME] = mock_utils_module
# --- End of Pre-emptive Mocking ---

# Now it's safe to import your script's functions.
import copy_to_clipboard # Assuming your script is named copy_to_clipboard.py

# Helper function to create dummy files for tests
def create_dummy_file(tmp_path: Path, filename: str, content: str = "", subfolder: str = None) -> Path:
    target_dir = tmp_path
    if subfolder:
        target_dir = tmp_path / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
    file = target_dir / filename
    file.write_text(content, encoding="utf-8")
    return file

# --- Test Cases ---

def test_single_file_raw_copy_default(tmp_path: Path, mocker, capsys):
    """Test copying a single file (default) results in raw content."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    file_content = "Hello, World!\nThis is a single file."
    single_file_path = create_dummy_file(tmp_path, "single.txt", file_content)
    mock_get_clipboard.return_value = file_content

    copy_to_clipboard.copy_files_to_clipboard([str(single_file_path)])

    mock_set_clipboard.assert_called_once_with(file_content)
    mock_get_clipboard.assert_called_once()

    captured = capsys.readouterr()
    assert f"[INFO] Successfully read '{single_file_path}'." in captured.out
    assert f"raw content from 1 file ('{single_file_path}') (2 lines total)" in captured.out
    assert "[SUCCESS] Clipboard copy complete and content verified." in captured.out
    assert "[CHANGES]" not in captured.out # Default behavior

def test_single_empty_file_raw_copy_default(tmp_path: Path, mocker, capsys):
    """Test copying a single empty file (default)."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    empty_file_path = create_dummy_file(tmp_path, "empty.txt", "")
    mock_get_clipboard.return_value = ""

    copy_to_clipboard.copy_files_to_clipboard([str(empty_file_path)])

    mock_set_clipboard.assert_called_once_with("")
    mock_get_clipboard.assert_called_once()

    captured = capsys.readouterr()
    assert f"[INFO] Successfully read '{empty_file_path}'." in captured.out
    assert f"raw content from 1 file ('{empty_file_path}') (0 lines total)" in captured.out
    assert "[SUCCESS] Clipboard copy complete and content verified." in captured.out
    assert "[CHANGES]" not in captured.out

def test_single_file_not_found(tmp_path: Path, mocker, capsys):
    """Test behavior when a single specified file (default raw mode) is not found."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    
    non_existent_file = tmp_path / "notfound.txt"
    copy_to_clipboard.copy_files_to_clipboard([str(non_existent_file)])

    mock_set_clipboard.assert_not_called()
    captured = capsys.readouterr()
    assert f"[ERROR] File not found: '{non_existent_file}'. Nothing will be copied." in captured.out

def test_multiple_files_wrapped_copy_default(tmp_path: Path, mocker, capsys, monkeypatch):
    """Test copying multiple files (default) results in wrapped content with relative paths."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    
    # Change CWD to tmp_path to make relpath predictable
    monkeypatch.chdir(tmp_path)

    file1_content = "Content of file1."
    file2_content = "Content of file2.\nThis has two lines."
    
    # Create files directly in tmp_path (which is now CWD)
    file1_path = create_dummy_file(tmp_path, "file1.txt", file1_content)
    file2_path = create_dummy_file(tmp_path, "file2.txt", file2_content)

    # Relative paths from tmp_path (which is CWD)
    rel_file1_path = os.path.relpath(file1_path) # Should be "file1.txt"
    rel_file2_path = os.path.relpath(file2_path) # Should be "file2.txt"

    block1 = f"{rel_file1_path}\n```\n{file1_content}\n```"
    block2 = f"{rel_file2_path}\n```\n{file2_content}\n```"
    expected_clipboard_content = f"{block1}\n\n{block2}"
    mock_get_clipboard.return_value = expected_clipboard_content

    copy_to_clipboard.copy_files_to_clipboard([str(file1_path), str(file2_path)])

    mock_set_clipboard.assert_called_once_with(expected_clipboard_content)
    mock_get_clipboard.assert_called_once()

    captured = capsys.readouterr()
    assert f"[INFO] Processed '{file1_path}' into code block." in captured.out
    assert f"[INFO] Processed '{file2_path}' into code block." in captured.out
    expected_lines_count = len(expected_clipboard_content.splitlines())
    assert f"wrapped content from 2 of 2 file(s) ({expected_lines_count} lines total)" in captured.out
    assert "[SUCCESS] Clipboard copy complete and content verified." in captured.out
    assert "[CHANGES]" in captured.out
    assert "- Wrapping content of 2 file(s) in code blocks with relative paths" in captured.out

def test_single_file_force_wrap(tmp_path: Path, mocker, capsys, monkeypatch):
    """Test single file with --force-wrap."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)

    file_content = "Single wrapped content."
    file_path = create_dummy_file(tmp_path, "wrap_me.txt", file_content)
    rel_file_path = os.path.relpath(file_path)
    
    expected_clipboard_content = f"{rel_file_path}\n```\n{file_content}\n```"
    mock_get_clipboard.return_value = expected_clipboard_content

    copy_to_clipboard.copy_files_to_clipboard([str(file_path)], force_wrap=True)

    mock_set_clipboard.assert_called_once_with(expected_clipboard_content)
    captured = capsys.readouterr()
    assert f"[INFO] Processed '{file_path}' into code block." in captured.out
    assert "[CHANGES]" in captured.out
    assert "- Forced wrapping of single file in code block" in captured.out
    assert "- Wrapping content of 1 file(s) in code blocks with relative paths" in captured.out # This also applies

def test_single_file_force_wrap_show_full_path(tmp_path: Path, mocker, capsys, monkeypatch):
    """Test single file with --force-wrap and --show-full-path."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)

    file_content = "Full path wrapped."
    file_path_obj = create_dummy_file(tmp_path, "full_wrap.txt", file_content, subfolder="sub")
    
    # Need to pass the string representation of the path to the function
    file_path_str = str(file_path_obj)
    
    abs_file_path = os.path.abspath(file_path_obj)
    rel_file_path = os.path.relpath(file_path_obj) # Will be "sub/full_wrap.txt" if CWD is tmp_path

    expected_clipboard_content = f"{abs_file_path}\n{rel_file_path}\n```\n{file_content}\n```"
    mock_get_clipboard.return_value = expected_clipboard_content

    copy_to_clipboard.copy_files_to_clipboard([file_path_str], force_wrap=True, show_full_path=True)

    mock_set_clipboard.assert_called_once_with(expected_clipboard_content)
    captured = capsys.readouterr()
    assert f"[INFO] Processed '{file_path_str}' into code block." in captured.out
    assert "[CHANGES]" in captured.out
    assert "- Forced wrapping of single file in code block" in captured.out
    assert "- Wrapping content of 1 file(s) in code blocks with relative paths" in captured.out
    assert "- Displaying full absolute paths above each code block" in captured.out

def test_multiple_files_show_full_path(tmp_path: Path, mocker, capsys, monkeypatch):
    """Test multiple files with --show-full-path."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)

    file1_content = "Content file 1"
    file2_content = "Content file 2"
    file1_path_obj = create_dummy_file(tmp_path, "f1.txt", file1_content, subfolder="dir1")
    file2_path_obj = create_dummy_file(tmp_path, "f2.txt", file2_content, subfolder="dir2")

    file1_path_str = str(file1_path_obj)
    file2_path_str = str(file2_path_obj)

    abs_f1 = os.path.abspath(file1_path_obj)
    rel_f1 = os.path.relpath(file1_path_obj)
    abs_f2 = os.path.abspath(file2_path_obj)
    rel_f2 = os.path.relpath(file2_path_obj)

    block1 = f"{abs_f1}\n{rel_f1}\n```\n{file1_content}\n```"
    block2 = f"{abs_f2}\n{rel_f2}\n```\n{file2_content}\n```"
    expected_clipboard_content = f"{block1}\n\n{block2}"
    mock_get_clipboard.return_value = expected_clipboard_content

    copy_to_clipboard.copy_files_to_clipboard([file1_path_str, file2_path_str], show_full_path=True)
    
    mock_set_clipboard.assert_called_once_with(expected_clipboard_content)
    captured = capsys.readouterr()
    assert f"[INFO] Processed '{file1_path_str}' into code block." in captured.out
    assert f"[INFO] Processed '{file2_path_str}' into code block." in captured.out
    assert "[CHANGES]" in captured.out
    assert "- Wrapping content of 2 file(s) in code blocks with relative paths" in captured.out
    assert "- Displaying full absolute paths above each code block" in captured.out

def test_single_file_raw_copy_explicit_arg(tmp_path: Path, mocker, capsys):
    """Test single file with --raw-copy argument."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    file_content = "Raw copy explicitly."
    file_path = create_dummy_file(tmp_path, "raw_explicit.txt", file_content)
    mock_get_clipboard.return_value = file_content

    # --raw-copy should override --force-wrap and --show-full-path
    copy_to_clipboard.copy_files_to_clipboard(
        [str(file_path)], raw_copy=True, force_wrap=True, show_full_path=True
    )

    mock_set_clipboard.assert_called_once_with(file_content)
    captured = capsys.readouterr()
    assert f"[INFO] Successfully read '{file_path}' for raw concatenation." in captured.out
    assert "[CHANGES]" in captured.out
    assert "- Raw copy mode enabled (filenames, paths, and wrapping are disabled)" in captured.out
    assert "Forced wrapping" not in captured.out # Should be overridden
    assert "Displaying full absolute paths" not in captured.out # Should be overridden

def test_multiple_files_raw_copy_explicit_arg(tmp_path: Path, mocker, capsys):
    """Test multiple files with --raw-copy argument."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    file1_content = "File one raw part."
    file2_content = "File two raw part."
    file1_path = create_dummy_file(tmp_path, "raw1.txt", file1_content)
    file2_path = create_dummy_file(tmp_path, "raw2.txt", file2_content)
    
    expected_clipboard_content = file1_content + file2_content
    mock_get_clipboard.return_value = expected_clipboard_content

    copy_to_clipboard.copy_files_to_clipboard(
        [str(file1_path), str(file2_path)], raw_copy=True, show_full_path=True
    )

    mock_set_clipboard.assert_called_once_with(expected_clipboard_content)
    captured = capsys.readouterr()
    assert f"[INFO] Successfully read '{file1_path}' for raw concatenation." in captured.out
    assert f"[INFO] Successfully read '{file2_path}' for raw concatenation." in captured.out
    assert "[CHANGES]" in captured.out
    assert "- Raw copy mode enabled (filenames, paths, and wrapping are disabled)" in captured.out
    assert "Wrapping content" not in captured.out # Should be overridden

def test_multiple_files_one_not_found_wrapped_mode(tmp_path: Path, mocker, capsys, monkeypatch):
    """Test multiple files, one not found, in default wrapped mode."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)

    file1_content = "Existing file content."
    file1_path = create_dummy_file(tmp_path, "exists.txt", file1_content)
    non_existent_file = tmp_path / "notfound.txt"
    
    rel_file1_path = os.path.relpath(file1_path)
    expected_clipboard_content = f"{rel_file1_path}\n```\n{file1_content}\n```"
    mock_get_clipboard.return_value = expected_clipboard_content

    copy_to_clipboard.copy_files_to_clipboard([str(file1_path), str(non_existent_file)])

    mock_set_clipboard.assert_called_once_with(expected_clipboard_content)
    captured = capsys.readouterr()
    assert f"[INFO] Processed '{file1_path}' into code block." in captured.out
    assert f"[WARNING] File not found: '{non_existent_file}'. Skipping this file." in captured.out
    expected_lines_count = len(expected_clipboard_content.splitlines())
    assert f"wrapped content from 1 of 2 file(s) ({expected_lines_count} lines total)" in captured.out
    assert "[CHANGES]" in captured.out

def test_multiple_files_all_not_found_wrapped_mode(tmp_path: Path, mocker, capsys):
    """Test multiple files, all not found, in default wrapped mode."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')

    non_existent1 = tmp_path / "notfound1.txt"
    non_existent2 = tmp_path / "notfound2.txt"

    copy_to_clipboard.copy_files_to_clipboard([str(non_existent1), str(non_existent2)])

    mock_set_clipboard.assert_not_called()
    captured = capsys.readouterr()
    assert f"[WARNING] File not found: '{non_existent1}'. Skipping this file." in captured.out
    assert f"[WARNING] File not found: '{non_existent2}'. Skipping this file." in captured.out
    assert "[INFO] No content was successfully processed from any of the files. Clipboard not updated." in captured.out

def test_multiple_files_all_not_found_raw_mode(tmp_path: Path, mocker, capsys):
    """Test multiple files, all not found, in --raw-copy mode."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')

    non_existent1 = tmp_path / "notfound1.txt"
    non_existent2 = tmp_path / "notfound2.txt"

    copy_to_clipboard.copy_files_to_clipboard([str(non_existent1), str(non_existent2)], raw_copy=True)

    mock_set_clipboard.assert_not_called()
    captured = capsys.readouterr()
    assert f"[WARNING] File not found: '{non_existent1}'. Skipping this file for raw concatenation." in captured.out
    assert f"[WARNING] File not found: '{non_existent2}'. Skipping this file for raw concatenation." in captured.out
    assert "[INFO] No content was successfully processed from any files. Clipboard not updated." in captured.out
    assert "[CHANGES]" in captured.out # Raw copy is a change from default
    assert "- Raw copy mode enabled" in captured.out


def test_validation_logic_truncated_clipboard(tmp_path: Path, mocker, capsys):
    """Test validation message for truncated clipboard content."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')

    file_content = "Line 1\nLine 2\nLine 3 is very long."
    single_file_path = create_dummy_file(tmp_path, "full.txt", file_content)
    truncated_content = "Line 1\nLine 2" # Simulates clipboard truncation
    mock_get_clipboard.return_value = truncated_content

    copy_to_clipboard.copy_files_to_clipboard([str(single_file_path)]) # Default single file

    mock_set_clipboard.assert_called_once_with(file_content)
    mock_get_clipboard.assert_called_once()
    captured = capsys.readouterr()
    assert "[WARNING] Clipboard content may be truncated or incomplete: 2 lines found in clipboard vs. 3 expected." in captured.out

def test_set_clipboard_not_implemented(tmp_path: Path, mocker, capsys):
    """Test error message if set_clipboard is not implemented."""
    mocker.patch.object(copy_to_clipboard, 'set_clipboard', side_effect=NotImplementedError("set_clipboard NI"))
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard') # Won't be called

    file_path = create_dummy_file(tmp_path, "test.txt", "content")
    copy_to_clipboard.copy_files_to_clipboard([str(file_path)])

    mock_get_clipboard.assert_not_called()
    captured = capsys.readouterr()
    assert "[ERROR] set_clipboard is not implemented in clipboard_utils. Cannot copy content." in captured.out

def test_get_clipboard_not_implemented(tmp_path: Path, mocker, capsys):
    """Test info message if get_clipboard is not implemented (for validation)."""
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mocker.patch.object(copy_to_clipboard, 'get_clipboard', side_effect=NotImplementedError("get_clipboard NI"))

    file_path = create_dummy_file(tmp_path, "validate.txt", "content")
    copy_to_clipboard.copy_files_to_clipboard([str(file_path)])

    mock_set_clipboard.assert_called_once()
    captured = capsys.readouterr()
    assert "[INFO] get_clipboard is not implemented in clipboard_utils. Skipping verification step." in captured.out

# To run these tests, save the script as copy_to_clipboard.py and the tests
# as test_copy_to_clipboard.py in the same directory (or ensure they are in PYTHONPATH)
# and run `pytest` from your terminal in that directory.
# You'll need pytest installed: `pip install pytest pytest-mock`
