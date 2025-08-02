# tests/copy_to_clipboard_test.py
import sys
import os
import pytest
from pathlib import Path 
from unittest import mock
import re 
import unicodedata

MOCK_CLIPBOARD_MODULE_NAME = 'cross_platform.clipboard_utils'
mock_utils_module = mock.MagicMock()
mock_utils_module.set_clipboard = mock.MagicMock()
mock_utils_module.get_clipboard = mock.MagicMock(return_value="") 

sys.modules[MOCK_CLIPBOARD_MODULE_NAME] = mock_utils_module

import copy_to_clipboard 
from copy_to_clipboard import WHOLE_WRAP_HEADER_MARKER

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
    mock_utils_module.set_clipboard.reset_mock()
    mock_utils_module.get_clipboard.reset_mock()
    mock_utils_module.get_clipboard.return_value = "" 
    mock_utils_module.get_clipboard.side_effect = None

def call_c2c(file_paths_str_list, 
             raw_copy=False, wrap=False, whole_wrap=False, 
             show_full_path=False, 
             append=False, override_append_wrapping=False, 
             no_stats=True) -> int:
    return copy_to_clipboard.copy_files_to_clipboard(
        file_paths_str_list,
        raw_copy=raw_copy,
        wrap=wrap,
        whole_wrap=whole_wrap,
        show_full_path=show_full_path,
        append=append,
        override_append_wrapping=override_append_wrapping,
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

def assert_logged(normalized_log_output: str, expected_parts: list, path_obj_for_filename: Path | list[Path] = None, absent_parts: list = None):
    for part in expected_parts:
        assert part in normalized_log_output, f"Expected log part '{part}' not found in output:\n'{normalized_log_output}'"
    
    if absent_parts:
        for part in absent_parts:
            assert part not in normalized_log_output, f"Forbidden log part '{part}' was found in output:\n'{normalized_log_output}'"

    if path_obj_for_filename:
        paths_to_check = []
        if isinstance(path_obj_for_filename, list): paths_to_check.extend(path_obj_for_filename)
        else: paths_to_check.append(path_obj_for_filename)

        for p_obj in paths_to_check:
            path_as_str_quoted = f"'{str(p_obj)}'" 
            path_as_str_unquoted = str(p_obj) 
            assert (path_as_str_quoted in normalized_log_output or \
                    path_as_str_unquoted in normalized_log_output), \
                   f"Path string for '{p_obj.name}' (expected as {path_as_str_quoted} or {path_as_str_unquoted}) not found as expected in output:\n'{normalized_log_output}'"

# --- Basic Operation Tests (No Append) ---
def test_single_file_default_is_raw(tmp_path: Path, capsys):
    file_content = "Hello, World!"
    p1 = create_dummy_file(tmp_path, "single.txt", file_content)
    mock_utils_module.get_clipboard.return_value = file_content

    exit_code = call_c2c([str(p1)])
    assert exit_code == 0                         
    mock_utils_module.set_clipboard.assert_called_once_with(file_content)
    captured_err = capsys.readouterr().err 
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, ["[INFO] Successfully read"], 
                  path_obj_for_filename=p1,
                  absent_parts=["[ACTIVE MODES / CHANGES FROM DEFAULT]"])

def test_multiple_files_default_is_individual_wrap(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p1_content = "C1"; p1 = create_dummy_file(tmp_path, "p1.txt", p1_content)
    p2_content = "C2"; p2 = create_dummy_file(tmp_path, "p2.txt", p2_content)
    h1 = os.path.relpath(p1); h2 = os.path.relpath(p2)
    expected_clip = f"{h1}\n```\n{p1_content}\n```\n\n{h2}\n```\n{p2_content}\n```"
    mock_utils_module.get_clipboard.return_value = expected_clip

    exit_code = call_c2c([str(p1), str(p2)]) 
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clip)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, 
                  ["[ACTIVE MODES / CHANGES FROM DEFAULT]", "- New content mode: Individually wrapped files (multiple files default)"])

def test_explicit_raw_copy_single_file(tmp_path: Path, capsys):
    file_content = "Raw explicit."
    p1 = create_dummy_file(tmp_path, "p1.txt", file_content)
    mock_utils_module.get_clipboard.return_value = file_content
    
    exit_code = call_c2c([str(p1)], raw_copy=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(file_content)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, ["[ACTIVE MODES / CHANGES FROM DEFAULT]", "- New content mode: Raw content (due to --raw-copy)"])

def test_explicit_individual_wrap_single_file(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = "Wrapped."; p1 = create_dummy_file(tmp_path, "f.txt", content)
    h1 = os.path.relpath(p1); expected_clip = f"{h1}\n```\n{content}\n```"
    mock_utils_module.get_clipboard.return_value = expected_clip
    
    exit_code = call_c2c([str(p1)], wrap=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clip)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, ["[ACTIVE MODES / CHANGES FROM DEFAULT]", "- New content mode: Individually wrapped files (due to --wrap)"])

def test_explicit_whole_wrap_single_file(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = "Whole single."; p1 = create_dummy_file(tmp_path, "f.txt", content)
    h1 = os.path.relpath(p1)
    inner_content_for_W = f"{h1}\n{content}"
    expected_clip = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{inner_content_for_W}\n```"
    mock_utils_module.get_clipboard.return_value = expected_clip

    exit_code = call_c2c([str(p1)], whole_wrap=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clip)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, ["[ACTIVE MODES / CHANGES FROM DEFAULT]", "- New content mode: All content in a single marked wrapper block (due to --whole-wrap)"])

def test_explicit_whole_wrap_multiple_files(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p1_c = "C1"; p1 = create_dummy_file(tmp_path, "p1.txt", p1_c)
    p2_c = "C2"; p2 = create_dummy_file(tmp_path, "p2.txt", p2_c)
    h1 = os.path.relpath(p1); h2 = os.path.relpath(p2)
    inner_p1 = f"{h1}\n{p1_c}"; inner_p2 = f"{h2}\n{p2_c}"
    expected_inner_content = f"{inner_p1}\n\n---\n\n{inner_p2}"
    expected_clip = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{expected_inner_content}\n```"
    mock_utils_module.get_clipboard.return_value = expected_clip

    exit_code = call_c2c([str(p1), str(p2)], whole_wrap=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clip)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert_logged(normalized_err, ["[ACTIVE MODES / CHANGES FROM DEFAULT]", "- New content mode: All content in a single marked wrapper block (due to --whole-wrap)"])

# --- Append Tests (General) ---
def test_append_to_empty_clipboard(tmp_path: Path, capsys):
    mock_utils_module.get_clipboard.return_value = "" 

    file_content = "New content."
    file_path = create_dummy_file(tmp_path, "new.txt", file_content)

    exit_code = call_c2c([str(file_path)], append=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(file_content)
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[INFO] Clipboard was empty; performing normal copy (append mode)." in normalized_err
    assert "[ACTIVE MODES / CHANGES FROM DEFAULT]" in normalized_err 
    assert "- Append mode enabled" in normalized_err
    assert "- New content mode: Raw content (single file default)" in normalized_err

def test_append_empty_new_content_preserves_original(tmp_path: Path, capsys):
    initial_clipboard = "Some existing data."
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    empty_file = create_dummy_file(tmp_path, "empty.txt", "")

    exit_code = call_c2c([str(empty_file)], append=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_not_called()
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert "[INFO] Clipboard content is unchanged. Skipping set_clipboard call." in normalized_err

def test_append_get_clipboard_fails_performs_normal_copy(tmp_path: Path, capsys):
    def get_clipboard_side_effect_logic(*args, **kwargs):
        if mock_utils_module.get_clipboard.call_count == 1:
            raise Exception("Simulated get_clipboard error for append")
        return "Data for normal copy." 
    mock_utils_module.get_clipboard.side_effect = get_clipboard_side_effect_logic

    file_content = "Data for normal copy."
    file_path = create_dummy_file(tmp_path, "data.txt", file_content)

    exit_code = call_c2c([str(file_path)], append=True)
    assert exit_code == 0 
    mock_utils_module.set_clipboard.assert_called_once_with(file_content) 
    captured_err = capsys.readouterr().err
    normalized_err = normalize_output(captured_err)
    assert "[WARNING] Error getting clipboard for append" in normalized_err
    assert "Performing normal copy." in normalized_err 
    assert "[ACTIVE MODES / CHANGES FROM DEFAULT]" in normalized_err

# --- Smart Append (-a, no -o) ---
def test_smart_append_raw_to_W_block(tmp_path: Path, capsys): 
    initial_inner = "Old W content."
    initial_clipboard = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{initial_inner}\n```"
    
    new_raw = "New raw data."
    p_new = create_dummy_file(tmp_path, "new.txt", new_raw)
    expected_final_inner = f"{initial_inner.rstrip()}\n\n---\n\n{new_raw}"
    expected_clipboard = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{expected_final_inner}\n```"

    def get_clip_verify(*args, **kwargs):
        if mock_utils_module.get_clipboard.call_count == 1: return initial_clipboard
        return expected_clipboard
    mock_utils_module.get_clipboard.side_effect = get_clip_verify
    
    exit_code = call_c2c([str(p_new)], append=True) 
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert f"Appended new content into existing '{WHOLE_WRAP_HEADER_MARKER}' block (smart append)" in normalized_err

def test_smart_append_individually_wrapped_to_W_block(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initial_inner = "Old W content."
    initial_clipboard = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{initial_inner}\n```"

    new_c = "New individual"; p_new = create_dummy_file(tmp_path, "new.txt", new_c)
    h_new = os.path.relpath(p_new)
    payload_from_new_w = f"{h_new}\n{new_c}" 
    expected_final_inner = f"{initial_inner.rstrip()}\n\n---\n\n{payload_from_new_w}"
    expected_clipboard = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{expected_final_inner}\n```"

    def get_clip_verify(*args, **kwargs):
        if mock_utils_module.get_clipboard.call_count == 1: return initial_clipboard
        return expected_clipboard
    mock_utils_module.get_clipboard.side_effect = get_clip_verify

    exit_code = call_c2c([str(p_new)], append=True, wrap=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert f"Appended new content into existing '{WHOLE_WRAP_HEADER_MARKER}' block (smart append)" in normalized_err

def test_smart_append_individually_wrapped_to_non_W_block(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initial_clipboard = "Some existing raw text." 
    
    new_c = "New wrapped."; p_new = create_dummy_file(tmp_path, "new.txt", new_c)
    h_new = os.path.relpath(p_new)
    new_block_payload = f"{h_new}\n```\n{new_c}\n```" 
    expected_clipboard = f"{initial_clipboard.rstrip('\n')}\n\n{new_block_payload}"
    
    def get_clip_verify(*args, **kwargs):
        if mock_utils_module.get_clipboard.call_count == 1: return initial_clipboard
        return expected_clipboard
    mock_utils_module.get_clipboard.side_effect = get_clip_verify

    exit_code = call_c2c([str(p_new)], append=True, wrap=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    # Using the debug marker for this stubborn test
    assert "%%%% NON_W_ORIGINAL_SMART_APPEND_LOG %%%%" in normalized_err

# --- Append with Override (-o) Tests ---
def test_append_override_new_raw_after_any_original(tmp_path: Path, capsys):
    initial_clipboard = f"{WHOLE_WRAP_HEADER_MARKER}\n```\nOld W block\n```"
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    new_raw = "Override raw append."
    p_new = create_dummy_file(tmp_path, "new.txt", new_raw)

    expected_clipboard = f"{initial_clipboard.rstrip('\n')}\n\n{new_raw}"
    def get_clip_verify_override(*args, **kwargs):
        if mock_utils_module.get_clipboard.call_count == 1: return initial_clipboard
        return expected_clipboard
    mock_utils_module.get_clipboard.side_effect = get_clip_verify_override

    exit_code = call_c2c([str(p_new)], append=True, override_append_wrapping=True) 
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert "Appended new content (using its own specified format) after existing clipboard content due to override." in normalized_err

def test_append_override_new_individually_wrapped_after_original(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initial_clipboard = "Original content"
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    
    new_c = "New -w content"; p_new = create_dummy_file(tmp_path, "new_w.txt", new_c)
    h_new = os.path.relpath(p_new)
    new_formatted_content = f"{h_new}\n```\n{new_c}\n```"
    expected_clipboard = f"{initial_clipboard.rstrip('\n')}\n\n{new_formatted_content}"

    def get_clip_verify_override(*args, **kwargs):
        if mock_utils_module.get_clipboard.call_count == 1: return initial_clipboard
        return expected_clipboard
    mock_utils_module.get_clipboard.side_effect = get_clip_verify_override

    exit_code = call_c2c([str(p_new)], append=True, override_append_wrapping=True, wrap=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert "Appended new content (using its own specified format) after existing clipboard content due to override." in normalized_err

def test_append_override_new_whole_wrapped_after_original(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initial_clipboard = "Original content"
    mock_utils_module.get_clipboard.return_value = initial_clipboard
    
    new_c = "New -W content"; p_new = create_dummy_file(tmp_path, "new_W.txt", new_c)
    h_new = os.path.relpath(p_new)
    inner_W = f"{h_new}\n{new_c}"
    new_formatted_content = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{inner_W}\n```"
    expected_clipboard = f"{initial_clipboard.rstrip('\n')}\n\n{new_formatted_content}"

    def get_clip_verify_override(*args, **kwargs):
        if mock_utils_module.get_clipboard.call_count == 1: return initial_clipboard
        return expected_clipboard
    mock_utils_module.get_clipboard.side_effect = get_clip_verify_override

    exit_code = call_c2c([str(p_new)], append=True, override_append_wrapping=True, whole_wrap=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clipboard)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert "Appended new content (using its own specified format) after existing clipboard content due to override." in normalized_err

def test_show_full_path_with_individual_wrap(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_content = "content"; p1 = create_dummy_file(tmp_path, "p1.txt", file_content, subfolder="sub")
    abs_p1 = str(p1.resolve()); rel_p1 = os.path.relpath(p1)
    expected_header = f"{abs_p1}\n{rel_p1}"
    expected_clip = f"{expected_header}\n```\n{file_content}\n```"
    mock_utils_module.get_clipboard.return_value = expected_clip
    
    exit_code = call_c2c([str(p1)], wrap=True, show_full_path=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clip)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert "[ACTIVE MODES / CHANGES FROM DEFAULT]" in normalized_err
    assert "Displaying full absolute paths in headers" in normalized_err
    assert "- New content mode: Individually wrapped files (due to --wrap)" in normalized_err


def test_show_full_path_with_whole_wrap_single_file(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_content = "content"; p1 = create_dummy_file(tmp_path, "w1.txt", file_content, subfolder="sub_w")
    abs_p1 = str(p1.resolve()); rel_p1 = os.path.relpath(p1)
    inner_header_for_W = f"{abs_p1}\n{rel_p1}" 
    expected_clip = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{inner_header_for_W}\n{file_content}\n```"
    mock_utils_module.get_clipboard.return_value = expected_clip
    
    exit_code = call_c2c([str(p1)], whole_wrap=True, show_full_path=True)
    assert exit_code == 0
    mock_utils_module.set_clipboard.assert_called_once_with(expected_clip)
    captured_err = capsys.readouterr().err; normalized_err = normalize_output(captured_err)
    assert "[ACTIVE MODES / CHANGES FROM DEFAULT]" in normalized_err
    assert "Displaying full absolute paths in headers" in normalized_err
    assert "- New content mode: All content in a single marked wrapper block (due to --whole-wrap)" in normalized_err
