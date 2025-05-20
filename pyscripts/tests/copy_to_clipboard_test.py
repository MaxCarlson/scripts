# tests/copy_to_clipboard_test.py
import sys
import os
import pytest
from pathlib import Path
from unittest import mock
import re # For ANSI code stripping
import unicodedata # For broader normalization

MOCK_CLIPBOARD_MODULE_NAME = 'cross_platform.clipboard_utils'
mock_utils_module = mock.MagicMock()
mock_utils_module.set_clipboard = mock.MagicMock()
mock_utils_module.get_clipboard = mock.MagicMock(return_value="") # Default empty

sys.modules[MOCK_CLIPBOARD_MODULE_NAME] = mock_utils_module

import copy_to_clipboard # Script under test

def create_dummy_file(tmp_path: Path, filename: str, content: str = "", subfolder: str = None) -> Path:
    target_dir = tmp_path
    if subfolder:
        target_dir = tmp_path / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
    file = target_dir / filename
    file.write_text(content, encoding="utf-8")
    return file

@pytest.fixture(autouse=True)
def reset_clipboard_mocks_between_tests():
    """Ensures clipboard mocks are fresh for each test."""
    mock_utils_module.set_clipboard.reset_mock()
    mock_utils_module.get_clipboard.reset_mock()
    mock_utils_module.get_clipboard.return_value = "" # Default
    mock_utils_module.get_clipboard.side_effect = None
    # Remove any test-specific flags
    if hasattr(mock_utils_module.get_clipboard, '_return_value_explicitly_set_by_test'):
        delattr(mock_utils_module.get_clipboard, '_return_value_explicitly_set_by_test')
    if hasattr(mock_utils_module.get_clipboard, '_side_effect_explicitly_set_by_test'):
        delattr(mock_utils_module.get_clipboard, '_side_effect_explicitly_set_by_test')


def call_c2c(file_paths_str_list, show_full_path=False, force_wrap=False, raw_copy=False, append=False, no_stats=True) -> int:
    # Mocks are reset by the autouse fixture.
    # Tests needing specific get_clipboard behavior will set it directly on mock_utils_module.get_clipboard
    # before calling call_c2c.
    return copy_to_clipboard.copy_files_to_clipboard(
        file_paths_str_list,
        show_full_path=show_full_path,
        force_wrap=force_wrap,
        raw_copy=raw_copy,
        append=append,
        no_stats=no_stats
    )

def normalize_output(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text_no_ansi = ansi_escape.sub('', text)
    text_unicode_normalized = unicodedata.normalize('NFKC', text_no_ansi)
    text_no_invisible = text_unicode_normalized.replace('\u200B', '')
    text_quotes_normalized = text_no_invisible.replace("‘", "'").replace("’", "'").replace("`", "'")
    text_no_newlines = text_quotes_normalized.replace('\n', '')
    text_normalized_space = re.sub(r'\s+', ' ', text_no_newlines)
    return text_normalized_space.strip()

def assert_logged(normalized_log_output: str, expected_parts: list, path_obj_for_filename: Path | list[Path] = None):
    for part in expected_parts:
        assert part in normalized_log_output, f"Expected log part '{part}' not found in output:\n'{normalized_log_output}'"
    
    if path_obj_for_filename:
        paths_to_check = []
        if isinstance(path_obj_for_filename, list):
            paths_to_check.extend(path_obj_for_filename)
        else:
            paths_to_check.append(path_obj_for_filename)

        for p_obj in paths_to_check:
            path_as_str_quoted = f"'{str(p_obj)}'"
            path_as_str_unquoted = str(p_obj)

            assert (path_as_str_quoted in normalized_log_output or \
                    path_as_str_unquoted in normalized_log_output), \
                   f"Path string for '{p_obj.name}' (expected as {path_as_str_quoted} or {path_as_str_unquoted}) not found as expected in output:\n'{normalized_log_output}'"

# --- Test Cases ---
# (Existing passing tests remain unchanged)

def test_single_file_raw_copy_default(tmp_path: Path, mocker, capsys):
    # No change to mocker.patch needed here, using global mock_utils_module
    file_content = "Hello, World!\nThis is a single file."
    single_file_path = create_dummy_file(tmp_path, "single.txt", file_content)
    mock_utils_module.get_clipboard.return_value = file_content 

    exit_code = call_c2c([str(single_file_path)]) 
    assert exit_code == 0                         

    mock_utils_module.set_clipboard.assert_called_once_with(file_content)
    # get_clipboard is called once for verification
    assert mock_utils_module.get_clipboard.call_count >= 1 
    captured_err = capsys.readouterr().err 
    normalized_err = normalize_output(captured_err)
    
    assert_logged(normalized_err, [
        "[INFO] Processing single file for raw copy:", 
        "[INFO] Successfully read",
        ".", # This dot is part of "Successfully read '{path}'."
        "[SUCCESS] Clipboard copy complete and content verified."
    ], path_obj_for_filename=single_file_path)


def test_single_empty_file_raw_copy_default(tmp_path: Path, mocker, capsys):
    empty_file_path = create_dummy_file(tmp_path, "empty.txt", "")
    mock_utils_module.get_clipboard.return_value = "" 

    exit_code = call_c2c([str(empty_file_path)]) 
    assert exit_code == 0                        

    mock_utils_module.set_clipboard.assert_called_once_with("") 
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Processing single file for raw copy:",
        "[INFO] Successfully read",
        ".", 
        "[SUCCESS] Clipboard copy complete and content verified."
    ], path_obj_for_filename=empty_file_path)

def test_single_file_not_found(tmp_path: Path, mocker, capsys):
    non_existent_file = tmp_path / "notfound.txt"
    
    exit_code = call_c2c([str(non_existent_file)]) 
    assert exit_code == 1                         

    mock_utils_module.set_clipboard.assert_not_called()
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    
    assert_logged(normalized_err, [
        "[INFO] Processing single file for raw copy:",
        "[ERROR] File not found:", 
        "Nothing will be copied."
    ], path_obj_for_filename=non_existent_file)


def test_multiple_files_wrapped_copy_default(tmp_path: Path, mocker, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f1_c = "Content1."; f2_c = "Content2.\nTwo lines."
    f1_p = create_dummy_file(tmp_path, "f1.txt", f1_c)
    f2_p = create_dummy_file(tmp_path, "f2.txt", f2_c)
    
    rel_f1 = os.path.relpath(f1_p, tmp_path); rel_f2 = os.path.relpath(f2_p, tmp_path)
    expected = f"{rel_f1}\n```\n{f1_c}\n```\n\n{rel_f2}\n```\n{f2_c}\n```"
    mock_utils_module.get_clipboard.return_value = expected 

    exit_code = call_c2c([str(f1_p), str(f2_p)]) 
    assert exit_code == 0                        

    mock_utils_module.set_clipboard.assert_called_once_with(expected)
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    
    assert_logged(normalized_err, [
        "[INFO] Processing 2 file(s) for aggregated copy with code fences.",
        "[INFO] Processed", "into code block.", 
        "[CHANGES FROM DEFAULT BEHAVIOR]",
        "- Wrapping content of 2 file(s) in code blocks with relative paths"
    ], path_obj_for_filename=[f1_p, f2_p])


def test_single_file_force_wrap(tmp_path: Path, mocker, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f_content = "Single wrapped."; f_path = create_dummy_file(tmp_path, "wrap.txt", f_content)
    expected = f"{os.path.relpath(f_path, tmp_path)}\n```\n{f_content}\n```"
    mock_utils_module.get_clipboard.return_value = expected

    exit_code = call_c2c([str(f_path)], force_wrap=True) 
    assert exit_code == 0                               

    mock_utils_module.set_clipboard.assert_called_once_with(expected)
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Processing 1 file(s) for aggregated copy with code fences.",
        "[INFO] Processed", "into code block.",
        "- Forced wrapping of single file in code block"
    ], path_obj_for_filename=f_path)

def test_single_file_force_wrap_show_full_path(tmp_path: Path, mocker, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f_obj = create_dummy_file(tmp_path, "fw_sfp.txt", "Full path wrapped.", subfolder="sub")
    expected_rel_path = os.path.relpath(f_obj, tmp_path)
    expected = f"{f_obj.resolve()}\n{expected_rel_path}\n```\nFull path wrapped.\n```"
    mock_utils_module.get_clipboard.return_value = expected

    exit_code = call_c2c([str(f_obj)], force_wrap=True, show_full_path=True) 
    assert exit_code == 0                                                    

    mock_utils_module.set_clipboard.assert_called_once_with(expected)
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Processing 1 file(s) for aggregated copy with code fences.",
        "[INFO] Processed", "into code block.",
        "- Displaying full absolute paths above each code block"
    ], path_obj_for_filename=f_obj)

def test_multiple_files_show_full_path(tmp_path: Path, mocker, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f1 = create_dummy_file(tmp_path, "mf1.txt", "C1", subfolder="d1")
    f2 = create_dummy_file(tmp_path, "mf2.txt", "C2", subfolder="d2")
    expected_rel_f1 = os.path.relpath(f1, tmp_path)
    expected_rel_f2 = os.path.relpath(f2, tmp_path)
    expected = f"{f1.resolve()}\n{expected_rel_f1}\n```\nC1\n```\n\n{f2.resolve()}\n{expected_rel_f2}\n```\nC2\n```"
    mock_utils_module.get_clipboard.return_value = expected
    
    exit_code = call_c2c([str(f1), str(f2)], show_full_path=True) 
    assert exit_code == 0                                        
    
    mock_utils_module.set_clipboard.assert_called_once_with(expected)
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Processing 2 file(s) for aggregated copy with code fences.",
        "[INFO] Processed", "into code block.",
        "- Displaying full absolute paths above each code block"
    ], path_obj_for_filename=[f1,f2])

def test_single_file_raw_copy_explicit_arg(tmp_path: Path, mocker, capsys):
    f_content = "Raw copy explicit."; f_path = create_dummy_file(tmp_path, "raw_expl.txt", f_content)
    mock_utils_module.get_clipboard.return_value = f_content

    exit_code = call_c2c([str(f_path)], raw_copy=True) 
    assert exit_code == 0                              

    mock_utils_module.set_clipboard.assert_called_once_with(f_content)
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Raw copy mode active. Processing 1 file(s) for raw concatenation.",
        "[INFO] Successfully read", "for raw concatenation.",
        "- Raw copy mode enabled"
    ], path_obj_for_filename=f_path)

def test_multiple_files_raw_copy_explicit_arg(tmp_path: Path, mocker, capsys):
    f1_c="R1."; f2_c="R2."
    f1 = create_dummy_file(tmp_path, "mr1.txt", f1_c); f2 = create_dummy_file(tmp_path, "mr2.txt", f2_c)
    expected = f1_c + f2_c
    mock_utils_module.get_clipboard.return_value = expected

    exit_code = call_c2c([str(f1), str(f2)], raw_copy=True) 
    assert exit_code == 0                                   

    mock_utils_module.set_clipboard.assert_called_once_with(expected)
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Raw copy mode active. Processing 2 file(s) for raw concatenation.",
        "[INFO] Successfully read", "for raw concatenation.",
        "- Raw copy mode enabled"
    ], path_obj_for_filename=[f1, f2])


def test_multiple_files_one_not_found_wrapped_mode(tmp_path: Path, mocker, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f1 = create_dummy_file(tmp_path, "exists.txt", "Existing")
    non_existent = tmp_path / "notfound.txt"
    expected = f"{os.path.relpath(f1,tmp_path)}\n```\nExisting\n```"
    mock_utils_module.get_clipboard.return_value = expected

    exit_code = call_c2c([str(f1), str(non_existent)]) 
    assert exit_code == 0 

    mock_utils_module.set_clipboard.assert_called_once_with(expected)
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    
    assert "[INFO] Processed" in normalized_err and "into code block." in normalized_err 
    assert "[WARNING] File not found:" in normalized_err and ". Skipping this file." in normalized_err 
    assert_logged(normalized_err, [
        "[INFO] Processing 2 file(s) for aggregated copy with code fences.",
        "- Wrapping content of 1 file(s) in code blocks with relative paths"
    ], path_obj_for_filename=[f1, non_existent])

def test_multiple_files_all_not_found_wrapped_mode(tmp_path: Path, mocker, capsys):
    nf1 = tmp_path / "nf1.txt"; nf2 = tmp_path / "nf2.txt"

    exit_code = call_c2c([str(nf1), str(nf2)]) 
    assert exit_code == 1                      

    mock_utils_module.set_clipboard.assert_not_called()
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Processing 2 file(s) for aggregated copy with code fences.",
        "[WARNING] File not found:", ". Skipping this file.",
        "[INFO] No content successfully processed from any files. Clipboard not updated.",
        "- Wrapping content of 2 file(s) in code blocks with relative paths" 
    ], path_obj_for_filename=[nf1, nf2])


def test_multiple_files_all_not_found_raw_mode(tmp_path: Path, mocker, capsys):
    nf1 = tmp_path / "nf1.txt"; nf2 = tmp_path / "nf2.txt"

    exit_code = call_c2c([str(nf1), str(nf2)], raw_copy=True) 
    assert exit_code == 1                                     

    mock_utils_module.set_clipboard.assert_not_called()
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Raw copy mode active. Processing 2 file(s) for raw concatenation.",
        "[WARNING] File not found:", ". Skipping.",
        "[INFO] No content successfully processed from any files. Clipboard not updated.",
        "- Raw copy mode enabled (filenames, paths, and wrapping are disabled)"
    ], path_obj_for_filename=[nf1, nf2])

def test_validation_logic_truncated_clipboard(tmp_path: Path, mocker, capsys):
    f_content = "L1\nL2\nL3."; f_path = create_dummy_file(tmp_path, "full.txt", f_content)
    mock_utils_module.get_clipboard.return_value = "L1\nL2"

    exit_code = call_c2c([str(f_path)]) 
    assert exit_code == 0               

    mock_utils_module.set_clipboard.assert_called_once_with(f_content)
    assert mock_utils_module.get_clipboard.call_count >= 1
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[WARNING] Clipboard content may be truncated/incomplete."
    ])

def test_set_clipboard_not_implemented(tmp_path: Path, mocker, capsys):
    # We patch set_clipboard on the SCRIPT's imported instance, not the global mock
    mocker.patch.object(copy_to_clipboard, 'set_clipboard', side_effect=NotImplementedError("set_clipboard NI"))
    f_path = create_dummy_file(tmp_path, "test.txt", "content")
    
    exit_code = call_c2c([str(f_path)]) 
    assert exit_code == 1               

    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    
    expected_error_msg = "[ERROR] set_clipboard is not implemented in clipboard_utils. Cannot copy content."
    assert_logged(normalized_err, [expected_error_msg])
    assert "[CRITICAL ERROR] set_clipboard NI" not in normalized_err


def test_get_clipboard_not_implemented_for_verification(tmp_path: Path, mocker, capsys):
    # Patch get_clipboard specifically on the script's imported instance for verification
    mocker.patch.object(copy_to_clipboard, 'get_clipboard', side_effect=NotImplementedError("get_clipboard NI for verification"))
    
    f_path = create_dummy_file(tmp_path, "validate.txt", "content")

    exit_code = call_c2c([str(f_path)]) 
    assert exit_code == 0 # Set might work, verification fails gracefully           

    # set_clipboard should still be called (using the global mock_utils_module.set_clipboard here)
    mock_utils_module.set_clipboard.assert_called_once_with("content")
    
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] get_clipboard not implemented. Skipping verification."
    ])

# --- START: New Test Cases for Append Feature ---

def test_append_to_empty_clipboard(tmp_path: Path, mocker, capsys):
    mock_utils_module.get_clipboard.return_value = "" 
    mock_utils_module.get_clipboard._return_value_explicitly_set_by_test = True # Mark that this test set it

    file_content = "New content."
    file_path = create_dummy_file(tmp_path, "new.txt", file_content)

    exit_code = call_c2c([str(file_path)], append=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(file_content)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[INFO] Clipboard was empty; performing normal copy (append mode)." in normalized_err
    # get_clipboard is called for append, then for verification
    assert mock_utils_module.get_clipboard.call_count >= 2


def test_append_raw_to_raw_clipboard(tmp_path: Path, mocker, capsys):
    initial_clipboard = "Old raw line 1\nOld raw line 2"
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    mock_utils_module.get_clipboard._return_value_explicitly_set_by_test = True

    new_content = "New raw stuff."
    file_path = create_dummy_file(tmp_path, "new_raw.txt", new_content)

    exit_code = call_c2c([str(file_path)], append=True)
    assert exit_code == 0
    expected_clipboard = f"{initial_clipboard.rstrip('\n')}\n\n{new_content}"
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[INFO] Appended new content to existing clipboard content with a newline separator." in normalized_err

def test_append_raw_to_single_block_clipboard(tmp_path: Path, mocker, capsys):
    initial_clipboard = "```python\nprint('hello')\n```"
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    mock_utils_module.get_clipboard._return_value_explicitly_set_by_test = True

    new_content = "print('world')" 
    file_path = create_dummy_file(tmp_path, "new_code.py", new_content)

    exit_code = call_c2c([str(file_path)], append=True) 
    assert exit_code == 0
    expected_clipboard = "```python\nprint('hello')\nprint('world')\n```" 
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[INFO] Appended new content into the last detected code block of existing clipboard content." in normalized_err

def test_append_wrapped_to_single_block_clipboard(tmp_path: Path, mocker, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initial_clipboard = "```text\nOLD DATA\n```"
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    mock_utils_module.get_clipboard._return_value_explicitly_set_by_test = True

    new_file_content = "new file material"
    new_file_path = create_dummy_file(tmp_path, "app.txt", new_file_content)
    
    exit_code = call_c2c([str(new_file_path)], append=True, force_wrap=True)
    assert exit_code == 0

    rel_new_file_path = os.path.relpath(new_file_path, tmp_path)
    new_content_as_wrapped = f"{rel_new_file_path}\n```\n{new_file_content}\n```"
    expected_clipboard = f"```text\nOLD DATA\n{new_content_as_wrapped}\n```"
    
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[INFO] Appended new content into the last detected code block of existing clipboard content." in normalized_err

def test_append_empty_new_content(tmp_path: Path, mocker, capsys):
    initial_clipboard = "Some existing data."
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    mock_utils_module.get_clipboard._return_value_explicitly_set_by_test = True

    empty_file_path = create_dummy_file(tmp_path, "empty_for_append.txt", "")

    exit_code = call_c2c([str(empty_file_path)], append=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(initial_clipboard) 
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[INFO] New content is empty, clipboard remains unchanged (append mode)." in normalized_err
    # The stats message "Skipped (new content was empty), clipboard unchanged" is not printed to stderr directly.

def test_append_get_clipboard_not_implemented(tmp_path: Path, mocker, capsys):
    # Simulate get_clipboard failing only for the append part
    def get_clipboard_side_effect(*args, **kwargs):
        # First call (for append) raises error, subsequent calls (for verification) work
        if mock_utils_module.get_clipboard.call_count == 1: # Or check a flag
            raise NotImplementedError("get_clipboard NI for append")
        return "Some data" # Fallback for verification if needed, or specific expected
    
    mock_utils_module.get_clipboard.side_effect = get_clipboard_side_effect
    mock_utils_module.get_clipboard._side_effect_explicitly_set_by_test = True # Mark for call_c2c

    file_content = "Some data"
    file_path = create_dummy_file(tmp_path, "data.txt", file_content)

    exit_code = call_c2c([str(file_path)], append=True)
    assert exit_code == 0 
    mock_utils_module.set_clipboard.assert_called_once_with(file_content) 
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[WARNING] Could not get clipboard content for append. Performing normal copy." in normalized_err
    # The stats message "Skipped (get_clipboard NI)..." is not printed to stderr directly.

def test_append_trailing_whitespace_in_block(tmp_path: Path, mocker, capsys):
    initial_clipboard = "```\nOLD\n```  \n  " 
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    mock_utils_module.get_clipboard._return_value_explicitly_set_by_test = True

    new_content = "NEW" 
    file_path = create_dummy_file(tmp_path, "new.txt", new_content)

    exit_code = call_c2c([str(file_path)], append=True)
    assert exit_code == 0
    expected_clipboard = "```\nOLD\nNEW\n```  \n  " 
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[INFO] Appended new content into the last detected code block" in normalized_err

def test_append_raw_copy_mode_to_block(tmp_path: Path, mocker, capsys):
    initial_clipboard = "```\nOLD\n```"
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    mock_utils_module.get_clipboard._return_value_explicitly_set_by_test = True

    new_content = "NEW RAW"
    file_path = create_dummy_file(tmp_path, "new.txt", new_content)

    exit_code = call_c2c([str(file_path)], append=True, raw_copy=True) 
    assert exit_code == 0
    expected_clipboard = f"{initial_clipboard.rstrip('\n')}\n\n{new_content}"
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[INFO] Appended new content to existing clipboard content with a newline separator." in normalized_err
    assert "Raw copy mode active" in normalized_err

# --- END: New Test Cases for Append Feature ---
