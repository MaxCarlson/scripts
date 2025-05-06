# tests/test_func_replacer.py
import pytest
from unittest.mock import patch, MagicMock
import sys
import os
import tempfile
import re # Needed for checking output

# Adjust import based on actual location if needed
import func_replacer
import rgcodeblock_lib as rgc_lib

try:
    from cross_platform.clipboard_utils import get_clipboard
except ImportError:
    MOCK_CLIPBOARD_CONTENT_FOR_DUMMY = ""
    def get_clipboard():
        print("Warning: Using dummy get_clipboard for test.", file=sys.stderr)
        return MOCK_CLIPBOARD_CONTENT_FOR_DUMMY
    if hasattr(func_replacer, 'get_clipboard'):
        func_replacer.get_clipboard = get_clipboard

MOCK_CLIPBOARD_CONTENT = ""

@pytest.fixture
def mock_clipboard(monkeypatch):
    global MOCK_CLIPBOARD_CONTENT
    MOCK_CLIPBOARD_CONTENT = ""
    def mock_get_clipboard_func(): return MOCK_CLIPBOARD_CONTENT
    # Patch where it's used
    monkeypatch.setattr(func_replacer, 'get_clipboard', mock_get_clipboard_func)
    def set_clipboard_content(content): global MOCK_CLIPBOARD_CONTENT; MOCK_CLIPBOARD_CONTENT = content
    return set_clipboard_content

@pytest.fixture
def temp_target_file():
    tf = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".py", encoding='utf-8')
    tf.close()
    yield tf.name
    if os.path.exists(tf.name): os.unlink(tf.name)

def run_func_replacer(args_list, capsys):
    if hasattr(rgc_lib, 'OPTIONAL_LIBRARY_NOTES'): rgc_lib.OPTIONAL_LIBRARY_NOTES.clear()
    with patch.object(sys, 'argv', ['func_replacer.py'] + args_list):
        exit_code = None
        try:
            func_replacer.main()
            exit_code = 0
        except SystemExit as e: exit_code = e.code
    captured = capsys.readouterr()
    return captured.out, captured.err, exit_code

# --- Test Data ---
PYTHON_TARGET_CONTENT_ORIGINAL = """
# file: target.py
# Line 2
def old_function_name(param): # Line 3 (0-idx: 2)
    '''Docstring for old func.''' # Line 4 (0-idx: 3)
    print("old stuff") # Line 5 (0-idx: 4)
    return param * 2 # Line 6 (0-idx: 5)

class AnotherClass: # Line 8 (0-idx: 7)
    def method(self): # Line 9 (0-idx: 8)
        print("in method") # Line 10 (0-idx: 9)
"""
NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME = """
def old_function_name(new_param):
    # Replaced content
    # With multiple lines
    return new_param * 100
"""
NEW_FUNC_FROM_CLIPBOARD_WITH_NEW_NAME = """
class NewShinyClass:
    '''A new class'''
    def sparkle(self):
        return True
"""
RUBY_TARGET_CONTENT_ORIGINAL = """
# target.rb
class MyTarget # line 2 (0-idx: 1)
  def method_to_replace(arg) # line 3 (0-idx: 2)
    puts "Original method: #{arg}" # Line 4 (0-idx: 3)
  end # line 5 (0-idx: 4)

  def other_method # line 7 (0-idx: 6)
    puts "Something else"
  end # line 9 (0-idx: 8)
end # Line 10 (0-idx: 9)
"""
NEW_RUBY_METHOD_CLIPBOARD = """
def method_to_replace(new_arg)
  # This is the replacement
  puts "Replacement says: #{new_arg.upcase}"
end
"""

# --- Tests ---

def test_replace_python_function_by_name_from_clipboard(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    def mock_py_extractor(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name": return lines[2:6], 2, 5
        return None, -1, -1
    with patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor): # Patch where used
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--yes"], capsys)
    assert code == 0, f"[BY NAME] Exit:{code}, Err:{err}, Out:{out}"
    assert f"Successfully replaced 'old_function_name'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "Replaced content" in updated_content and "old stuff" not in updated_content

def test_replace_infer_name_from_clipboard(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_WITH_NEW_NAME)
    target_content_for_test = """
class NewShinyClass: # Line 2 (idx 1)
    pass # Line 3 (idx 2)
def another_func(): pass"""
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(target_content_for_test)
    def mock_py_extractor_for_new(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "NewShinyClass": return lines[1:3], 1, 2 # Class definition block
        return None, -1, -1
    with patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor_for_new):
        out, err, code = run_func_replacer([str(temp_target_file), "--yes"], capsys) # No --name
    assert code == 0, f"[INFER NAME] Exit:{code}, Err:{err}, Out:{out}"
    assert "Inferred entity name to replace: 'NewShinyClass'" in out
    assert f"Successfully replaced 'NewShinyClass'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "'''A new class'''" in updated_content and "pass # Line 3" not in updated_content

def test_replace_using_source_file(mock_clipboard, temp_target_file, capsys):
    mock_clipboard("THIS SHOULD NOT BE USED")
    source_tf = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".py", encoding='utf-8')
    source_tf.write(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    source_tf.close()
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    def mock_py_extractor(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name": return lines[2:6], 2, 5
        return None, -1, -1
    with patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--source-file", source_tf.name, "--yes"], capsys)
    os.unlink(source_tf.name)
    assert code == 0
    assert f"Successfully replaced 'old_function_name'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "Replaced content" in updated_content and "THIS SHOULD NOT BE USED" not in updated_content

def test_replace_using_line_hint(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    def mock_py_extractor_for_line_hint(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name" and target_line_1idx == 3:
             return lines[2:6], 2, 5
        print(f"Debug Mock: Called with name={target_entity_name}, line={target_line_1idx}. No match.", file=sys.stderr)
        return None, -1, -1
    # Patch where it's looked up (in func_replacer's context)
    with patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor_for_line_hint) as mock_obj:
         out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--line", "3", "--yes"], capsys)
    assert code == 0, f"[LINE HINT] Exit:{code}, Err:{err}, Out:{out}" # Check error output if fails
    mock_obj.assert_called_once()
    call_args, call_kwargs = mock_obj.call_args
    assert call_kwargs.get('target_line_1idx') == 3
    assert call_kwargs.get('target_entity_name') == "old_function_name"
    assert f"Successfully replaced 'old_function_name'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "Replaced content" in updated_content

def test_target_entity_not_found(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    with patch('func_replacer.rgc_lib.extract_python_block_ast', return_value=(None, -1, -1)):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "non_existent_func", "--yes"], capsys)
    assert code == 1
    assert "Error: Could not find or extract" in err
    assert "non_existent_func" in err

def test_confirmation_prompt_no(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    def mock_py_extractor(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name": return lines[2:6], 2, 5
        return None, -1, -1
    with patch('builtins.input', return_value='n'), \
         patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name"], capsys)
    assert code == 0
    assert "Replacement aborted by user." in out # <<< CORRECTED ASSERTION
    original_content_norm = PYTHON_TARGET_CONTENT_ORIGINAL.replace('\r\n', '\n')
    assert open(temp_target_file, encoding='utf-8').read().replace('\r\n', '\n') == original_content_norm

def test_replace_ruby_method_by_name(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_RUBY_METHOD_CLIPBOARD)
    ruby_target_path = temp_target_file.replace(".py", ".rb")
    with open(ruby_target_path, 'w', encoding='utf-8') as f: f.write(RUBY_TARGET_CONTENT_ORIGINAL)
    def mock_ruby_extractor(lines, target_line_idx, target_name=None):
        if target_name == "method_to_replace": return lines[2:5], 2, 4 # lines 3-5, index 2-4
        return None, -1, -1
    with patch('func_replacer.rgc_lib.extract_ruby_block', side_effect=mock_ruby_extractor):
         out, err, code = run_func_replacer([ruby_target_path, "--name", "method_to_replace", "--yes"], capsys)
    assert code == 0, f"[RUBY] Failed with code {code}. Err: {err}"
    assert f"Successfully replaced 'method_to_replace'" in out
    updated_content = open(ruby_target_path, encoding='utf-8').read()
    assert "Replacement says:" in updated_content and "Original method:" not in updated_content
    os.unlink(ruby_target_path)

def test_backup_flag(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    original_content = PYTHON_TARGET_CONTENT_ORIGINAL
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(original_content)
    backup_file_path = temp_target_file + ".bak"
    if os.path.exists(backup_file_path): os.unlink(backup_file_path)
    def mock_py_extractor(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name": return lines[2:6], 2, 5
        return None, -1, -1
    with patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--yes", "--backup"], capsys)
    assert code == 0
    assert os.path.exists(backup_file_path), "Backup file was not created"
    assert open(backup_file_path, encoding='utf-8').read().replace('\r\n','\n') == original_content.replace('\r\n','\n')
    assert open(temp_target_file, encoding='utf-8').read().replace('\r\n','\n') != original_content.replace('\r\n','\n')
    os.unlink(backup_file_path)
