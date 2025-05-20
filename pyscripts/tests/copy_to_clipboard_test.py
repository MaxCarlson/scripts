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
mock_utils_module.get_clipboard = mock.MagicMock(return_value="")

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

def call_c2c(file_paths_str_list, show_full_path=False, force_wrap=False, raw_copy=False, no_stats=True) -> int:
    mock_utils_module.set_clipboard.reset_mock()
    mock_utils_module.get_clipboard.reset_mock()
    if not mock_utils_module.get_clipboard.side_effect and not mock_utils_module.get_clipboard.return_value:
         mock_utils_module.get_clipboard.return_value = ""
    return copy_to_clipboard.copy_files_to_clipboard(
        file_paths_str_list,
        show_full_path=show_full_path,
        force_wrap=force_wrap,
        raw_copy=raw_copy,
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
    """
    Checks if all expected string parts are present in the normalized log output.
    If path_obj_for_filename (or a list of them) is provided, also checks for 
    the presence of their string representations (typically quoted) in the log.
    """
    for part in expected_parts:
        assert part in normalized_log_output, f"Expected log part '{part}' not found in output:\n'{normalized_log_output}'"
    
    if path_obj_for_filename:
        paths_to_check = []
        if isinstance(path_obj_for_filename, list):
            paths_to_check.extend(path_obj_for_filename)
        else:
            paths_to_check.append(path_obj_for_filename)

        for p_obj in paths_to_check:
            # The script uses f"'{file_path_obj}'", so str(p_obj) gets quoted.
            path_as_str_quoted = f"'{str(p_obj)}'"
            
            # Simpler check if path_as_str was already part of an expected_part (less common with this pattern)
            path_as_str_unquoted = str(p_obj)

            assert (path_as_str_quoted in normalized_log_output or \
                    path_as_str_unquoted in normalized_log_output), \
                   f"Path string for '{p_obj.name}' (expected as {path_as_str_quoted} or {path_as_str_unquoted}) not found as expected in output:\n'{normalized_log_output}'"

# --- Test Cases ---

def test_single_file_raw_copy_default(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    file_content = "Hello, World!\nThis is a single file."
    single_file_path = create_dummy_file(tmp_path, "single.txt", file_content)
    mock_get_clipboard.return_value = file_content

    exit_code = call_c2c([str(single_file_path)]) 
    assert exit_code == 0                         

    mock_set_clipboard.assert_called_once_with(file_content)
    mock_get_clipboard.assert_called_once()
    captured_err = capsys.readouterr().err 
    normalized_err = normalize_output(captured_err)
    
    # Script logs: f"[INFO] Processing single file for raw copy: '{file_path_obj}'"
    # Script logs: f"[INFO] Successfully read '{file_path_obj}'." (for single, non-raw)
    # OR       : f"[INFO] Successfully read '{file_path_obj}' for raw concatenation." (for raw)
    assert_logged(normalized_err, [
        "[INFO] Processing single file for raw copy:", 
        "[INFO] Successfully read", # Generic part
        # For single file raw copy, it logs this:
        # console_info.print(f"[INFO] Successfully read '{file_path_obj}'.")
        # then for raw it's:
        # console_info.print(f"[INFO] Successfully read '{file_path_obj}' for raw concatenation.")
        # So if it's single file AND raw_copy=False, it's the first. If raw_copy=True, it's the second.
        # This test IS default single file, raw_copy=False (implied). So it hits the first message type.
        # Let's re-check the script logic for single file default:
        # elif is_single_file_input and not force_wrap: # This is the branch
        #    console_info.print(f"[INFO] Processing single file for raw copy: '{file_path_obj}'")
        #    ...
        #    console_info.print(f"[INFO] Successfully read '{file_path_obj}'.")
        ".", # This dot is part of "Successfully read '{path}'."
        "[SUCCESS] Clipboard copy complete and content verified."
    ], path_obj_for_filename=single_file_path)


def test_single_empty_file_raw_copy_default(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    empty_file_path = create_dummy_file(tmp_path, "empty.txt", "")
    mock_get_clipboard.return_value = ""

    exit_code = call_c2c([str(empty_file_path)]) 
    assert exit_code == 0                        

    mock_set_clipboard.assert_called_once_with("") 
    mock_get_clipboard.assert_called_once()
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Processing single file for raw copy:",
        "[INFO] Successfully read",
        ".", # From "Successfully read '{path}'."
        "[SUCCESS] Clipboard copy complete and content verified."
    ], path_obj_for_filename=empty_file_path)

def test_single_file_not_found(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    non_existent_file = tmp_path / "notfound.txt"
    
    exit_code = call_c2c([str(non_existent_file)]) 
    assert exit_code == 1                         

    mock_set_clipboard.assert_not_called()
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    
    assert_logged(normalized_err, [
        "[INFO] Processing single file for raw copy:",
        "[ERROR] File not found:", 
        "Nothing will be copied." # The dot is part of the message here
    ], path_obj_for_filename=non_existent_file)


def test_multiple_files_wrapped_copy_default(tmp_path: Path, mocker, capsys, monkeypatch):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)
    f1_c = "Content1."; f2_c = "Content2.\nTwo lines."
    f1_p = create_dummy_file(tmp_path, "f1.txt", f1_c)
    f2_p = create_dummy_file(tmp_path, "f2.txt", f2_c)
    
    rel_f1 = os.path.relpath(f1_p, tmp_path); rel_f2 = os.path.relpath(f2_p, tmp_path)
    expected = f"{rel_f1}\n```\n{f1_c}\n```\n\n{rel_f2}\n```\n{f2_c}\n```"
    mock_get_clipboard.return_value = expected

    exit_code = call_c2c([str(f1_p), str(f2_p)]) 
    assert exit_code == 0                        

    mock_set_clipboard.assert_called_once_with(expected)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    
    # Script logs: f"[INFO] Processed '{file_path_obj}' into code block."
    assert_logged(normalized_err, [
        "[INFO] Processing 2 file(s) for aggregated copy with code fences.",
        "[INFO] Processed", "into code block.", # Generic parts of the "Processed" message
        "[CHANGES FROM DEFAULT BEHAVIOR]",
        "- Wrapping content of 2 file(s) in code blocks with relative paths"
    ], path_obj_for_filename=[f1_p, f2_p])


def test_single_file_force_wrap(tmp_path: Path, mocker, capsys, monkeypatch):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)
    f_content = "Single wrapped."; f_path = create_dummy_file(tmp_path, "wrap.txt", f_content)
    expected = f"{os.path.relpath(f_path, tmp_path)}\n```\n{f_content}\n```"
    mock_get_clipboard.return_value = expected

    exit_code = call_c2c([str(f_path)], force_wrap=True) 
    assert exit_code == 0                               

    mock_set_clipboard.assert_called_once_with(expected)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    # Script logs: f"[INFO] Processed '{file_path_obj}' into code block."
    assert_logged(normalized_err, [
        "[INFO] Processing 1 file(s) for aggregated copy with code fences.",
        "[INFO] Processed", "into code block.",
        "- Forced wrapping of single file in code block"
    ], path_obj_for_filename=f_path)

def test_single_file_force_wrap_show_full_path(tmp_path: Path, mocker, capsys, monkeypatch):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)
    f_obj = create_dummy_file(tmp_path, "fw_sfp.txt", "Full path wrapped.", subfolder="sub")
    expected_rel_path = os.path.relpath(f_obj, tmp_path)
    expected = f"{f_obj.resolve()}\n{expected_rel_path}\n```\nFull path wrapped.\n```"
    mock_get_clipboard.return_value = expected

    exit_code = call_c2c([str(f_obj)], force_wrap=True, show_full_path=True) 
    assert exit_code == 0                                                    

    mock_set_clipboard.assert_called_once_with(expected)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Processing 1 file(s) for aggregated copy with code fences.",
        "[INFO] Processed", "into code block.",
        "- Displaying full absolute paths above each code block"
    ], path_obj_for_filename=f_obj)

def test_multiple_files_show_full_path(tmp_path: Path, mocker, capsys, monkeypatch):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)
    f1 = create_dummy_file(tmp_path, "mf1.txt", "C1", subfolder="d1")
    f2 = create_dummy_file(tmp_path, "mf2.txt", "C2", subfolder="d2")
    expected_rel_f1 = os.path.relpath(f1, tmp_path)
    expected_rel_f2 = os.path.relpath(f2, tmp_path)
    expected = f"{f1.resolve()}\n{expected_rel_f1}\n```\nC1\n```\n\n{f2.resolve()}\n{expected_rel_f2}\n```\nC2\n```"
    mock_get_clipboard.return_value = expected
    
    exit_code = call_c2c([str(f1), str(f2)], show_full_path=True) 
    assert exit_code == 0                                        
    
    mock_set_clipboard.assert_called_once_with(expected)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] Processing 2 file(s) for aggregated copy with code fences.",
        "[INFO] Processed", "into code block.",
        "- Displaying full absolute paths above each code block"
    ], path_obj_for_filename=[f1,f2])

def test_single_file_raw_copy_explicit_arg(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    f_content = "Raw copy explicit."; f_path = create_dummy_file(tmp_path, "raw_expl.txt", f_content)
    mock_get_clipboard.return_value = f_content

    exit_code = call_c2c([str(f_path)], raw_copy=True) 
    assert exit_code == 0                              

    mock_set_clipboard.assert_called_once_with(f_content)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    # Script logs: f"[INFO] Successfully read '{file_path_obj}' for raw concatenation."
    assert_logged(normalized_err, [
        "[INFO] Raw copy mode active. Processing 1 file(s) for raw concatenation.",
        "[INFO] Successfully read", "for raw concatenation.",
        "- Raw copy mode enabled"
    ], path_obj_for_filename=f_path)

def test_multiple_files_raw_copy_explicit_arg(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    f1_c="R1."; f2_c="R2."
    f1 = create_dummy_file(tmp_path, "mr1.txt", f1_c); f2 = create_dummy_file(tmp_path, "mr2.txt", f2_c)
    expected = f1_c + f2_c
    mock_get_clipboard.return_value = expected

    exit_code = call_c2c([str(f1), str(f2)], raw_copy=True) 
    assert exit_code == 0                                   

    mock_set_clipboard.assert_called_once_with(expected)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    # Script logs: f"[INFO] Successfully read '{file_path_obj}' for raw concatenation."
    assert_logged(normalized_err, [
        "[INFO] Raw copy mode active. Processing 2 file(s) for raw concatenation.",
        "[INFO] Successfully read", "for raw concatenation.",
        "- Raw copy mode enabled"
    ], path_obj_for_filename=[f1, f2])


def test_multiple_files_one_not_found_wrapped_mode(tmp_path: Path, mocker, capsys, monkeypatch):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    monkeypatch.chdir(tmp_path)
    f1 = create_dummy_file(tmp_path, "exists.txt", "Existing")
    non_existent = tmp_path / "notfound.txt"
    expected = f"{os.path.relpath(f1,tmp_path)}\n```\nExisting\n```"
    mock_get_clipboard.return_value = expected

    exit_code = call_c2c([str(f1), str(non_existent)]) 
    assert exit_code == 0 

    mock_set_clipboard.assert_called_once_with(expected)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    
    # We expect a "Processed" log for f1 and a "File not found" for non_existent
    # Ensure both generic parts are present
    assert "[INFO] Processed" in normalized_err and "into code block." in normalized_err
    assert "[WARNING] File not found:" in normalized_err and ". Skipping this file." in normalized_err
    # Then check that the specific paths are mentioned correctly with assert_logged
    assert_logged(normalized_err, [
        "[INFO] Processing 2 file(s) for aggregated copy with code fences.",
        "- Wrapping content of 1 file(s) in code blocks with relative paths"
    ], path_obj_for_filename=[f1, non_existent])

def test_multiple_files_all_not_found_wrapped_mode(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    nf1 = tmp_path / "nf1.txt"; nf2 = tmp_path / "nf2.txt"

    exit_code = call_c2c([str(nf1), str(nf2)]) 
    assert exit_code == 1                      

    mock_set_clipboard.assert_not_called()
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    # Script logs: f"[WARNING] File not found: '{file_path_obj}'. Skipping this file."
    assert_logged(normalized_err, [
        "[INFO] Processing 2 file(s) for aggregated copy with code fences.",
        "[WARNING] File not found:", ". Skipping this file.",
        "[INFO] No content successfully processed from any files. Clipboard not updated.",
        "- Wrapping content of 2 file(s) in code blocks with relative paths" 
    ], path_obj_for_filename=[nf1, nf2])


def test_multiple_files_all_not_found_raw_mode(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    nf1 = tmp_path / "nf1.txt"; nf2 = tmp_path / "nf2.txt"

    exit_code = call_c2c([str(nf1), str(nf2)], raw_copy=True) 
    assert exit_code == 1                                     

    mock_set_clipboard.assert_not_called()
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    # Script logs: f"[WARNING] File not found: '{file_path_obj}'. Skipping."
    assert_logged(normalized_err, [
        "[INFO] Raw copy mode active. Processing 2 file(s) for raw concatenation.",
        "[WARNING] File not found:", ". Skipping.",
        "[INFO] No content successfully processed from any files. Clipboard not updated.",
        "- Raw copy mode enabled (filenames, paths, and wrapping are disabled)"
    ], path_obj_for_filename=[nf1, nf2])

def test_validation_logic_truncated_clipboard(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mock_get_clipboard = mocker.patch.object(copy_to_clipboard, 'get_clipboard')
    f_content = "L1\nL2\nL3."; f_path = create_dummy_file(tmp_path, "full.txt", f_content)
    mock_get_clipboard.return_value = "L1\nL2" 

    exit_code = call_c2c([str(f_path)]) 
    assert exit_code == 0               

    mock_set_clipboard.assert_called_once_with(f_content)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[WARNING] Clipboard content may be truncated/incomplete."
    ])

def test_set_clipboard_not_implemented(tmp_path: Path, mocker, capsys):
    mocker.patch.object(copy_to_clipboard, 'set_clipboard', side_effect=NotImplementedError("set_clipboard NI"))
    f_path = create_dummy_file(tmp_path, "test.txt", "content")
    
    exit_code = call_c2c([str(f_path)]) 
    assert exit_code == 1               

    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    
    expected_error_msg = "[ERROR] set_clipboard is not implemented in clipboard_utils. Cannot copy content."
    assert_logged(normalized_err, [expected_error_msg])
    assert "[CRITICAL ERROR] set_clipboard NI" not in normalized_err


def test_get_clipboard_not_implemented(tmp_path: Path, mocker, capsys):
    mock_set_clipboard = mocker.patch.object(copy_to_clipboard, 'set_clipboard')
    mocker.patch.object(copy_to_clipboard, 'get_clipboard', side_effect=NotImplementedError("get_clipboard NI"))
    f_path = create_dummy_file(tmp_path, "validate.txt", "content")

    exit_code = call_c2c([str(f_path)]) 
    assert exit_code == 0               

    mock_set_clipboard.assert_called_once()
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, [
        "[INFO] get_clipboard not implemented. Skipping verification."
    ])
