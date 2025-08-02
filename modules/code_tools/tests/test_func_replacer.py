# tests/test_func_replacer.py
import pytest
from unittest.mock import patch, MagicMock
import sys; sys.path.append('.')
import os
import tempfile
import re
import shutil

import func_replacer
import rgcodeblock_lib as rgc_lib

try: from cross_platform.clipboard_utils import get_clipboard
except ImportError: MOCK_CLIPBOARD_CONTENT_FOR_DUMMY = ""; get_clipboard = lambda: MOCK_CLIPBOARD_CONTENT_FOR_DUMMY
if hasattr(func_replacer, 'get_clipboard'): func_replacer.get_clipboard = get_clipboard
MOCK_CLIPBOARD_CONTENT = ""

@pytest.fixture
def mock_clipboard(monkeypatch):
    global MOCK_CLIPBOARD_CONTENT; MOCK_CLIPBOARD_CONTENT = ""
    def mock_get_clipboard_func(): return MOCK_CLIPBOARD_CONTENT
    monkeypatch.setattr(func_replacer, 'get_clipboard', mock_get_clipboard_func)
    def set_clipboard_content(content): global MOCK_CLIPBOARD_CONTENT; MOCK_CLIPBOARD_CONTENT = content
    return set_clipboard_content

@pytest.fixture
def temp_target_file():
    tf = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".py", encoding='utf-8'); tf.close()
    yield tf.name
    if os.path.exists(tf.name): os.unlink(tf.name)

def run_func_replacer(args_list, capsys):
    if hasattr(rgc_lib, 'OPTIONAL_LIBRARY_NOTES'): rgc_lib.OPTIONAL_LIBRARY_NOTES.clear()
    with patch.object(sys, 'argv', ['func_replacer.py'] + args_list):
        exit_code = None
        try: func_replacer.main(); exit_code = 0
        except SystemExit as e: exit_code = e.code
    captured = capsys.readouterr()
    return captured.out, captured.err, exit_code

# --- Test Data --- (Same as before)
PYTHON_TARGET_CONTENT_ORIGINAL="""# file: target.py\n# Line 2\ndef old_function_name(param): # Line 3 (0-idx: 2)\n    '''Docstring for old func.''' # Line 4 (0-idx: 3)\n    print("old stuff") # Line 5 (0-idx: 4)\n    return param * 2 # Line 6 (0-idx: 5)\n\nclass AnotherClass: # Line 8 (0-idx: 7)\n    def method(self):\n        print("in method")\n"""
NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME="\ndef old_function_name(new_param):\n    # Replaced content\n    return new_param * 100\n"
NEW_FUNC_FROM_CLIPBOARD_WITH_NEW_NAME="\nclass NewShinyClass:\n    '''A new class'''\n    def sparkle(self):\n        return True\n"
RUBY_TARGET_CONTENT_ORIGINAL="# target.rb\nclass MyTarget\n  def method_to_replace(arg)\n    puts \"Original method: \#{arg}\"\n  end\n\n  def other_method\n    puts \"Something else\"\n  end\nend\n"
NEW_RUBY_METHOD_CLIPBOARD="\ndef method_to_replace(new_arg)\n  # This is the replacement\n  puts \"Replacement says: \#{new_arg.upcase}\"\nend\n"


# --- Tests ---

def test_replace_python_function_by_name_from_clipboard(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    def mock_py_extractor(*args, **kwargs):
        if kwargs.get('target_entity_name') == "old_function_name": return PYTHON_TARGET_CONTENT_ORIGINAL.splitlines(True)[2:6], 2, 5
        return None, -1, -1
    with patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--yes"], capsys)
    assert code == 0, f"[BY NAME] Exit:{code}, Err:{err}, Out:{out}"
    assert f"Successfully replaced 'old_function_name'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "Replaced content" in updated_content and "old stuff" not in updated_content

def test_replace_infer_name_from_clipboard(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_WITH_NEW_NAME)
    target_content_for_test = "# Target file\nclass NewShinyClass:\n    pass\ndef another(): pass"
    target_lines_local = target_content_for_test.splitlines(True)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(target_content_for_test)
    def mock_py_extractor_for_new(*args, **kwargs):
        if kwargs.get('target_entity_name') == "NewShinyClass": return target_lines_local[1:3], 1, 2
        return None, -1, -1
    with patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor_for_new):
        out, err, code = run_func_replacer([str(temp_target_file), "--yes"], capsys)
    assert code == 0, f"[INFER NAME] Exit:{code}, Err:{err}, Out:{out}"
    assert re.search(r"Inferred entity name to replace: 'NewShinyClass'", out)
    assert f"Successfully replaced 'NewShinyClass'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "'''A new class'''" in updated_content
    # Corrected assertion to check specific part of the file
    assert "pass" not in updated_content.split("def another")[0] # 'pass' from original NewShinyClass is gone

def test_replace_using_source_file(mock_clipboard, temp_target_file, capsys):
    mock_clipboard("THIS SHOULD NOT BE USED")
    source_tf = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".py", encoding='utf-8'); source_tf.write(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME); source_tf.close()
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    def mock_py_extractor(*args, **kwargs):
        if kwargs.get('target_entity_name') == "old_function_name": return PYTHON_TARGET_CONTENT_ORIGINAL.splitlines(True)[2:6], 2, 5
        return None, -1, -1
    with patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--source-file", source_tf.name, "--yes"], capsys)
    os.unlink(source_tf.name)
    assert code == 0; assert f"Successfully replaced 'old_function_name'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "Replaced content" in updated_content and "THIS SHOULD NOT BE USED" not in updated_content

def test_replace_using_line_hint(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    target_lines_local = PYTHON_TARGET_CONTENT_ORIGINAL.splitlines(True)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    def mock_py_extractor_for_line_hint(lines_arg, content_arg, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name" and target_line_1idx == 3:
             return target_lines_local[2:6], 2, 5 # Block for 'old_function_name'
        return None, -1, -1
    # Patch where it's used within func_replacer.py
    with patch('func_replacer.rgc_lib.EXTRACTOR_DISPATCH_MAP', 
               {"python": mock_py_extractor_for_line_hint, **rgc_lib.EXTRACTOR_DISPATCH_MAP}) as mock_dispatch_map, \
         patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor_for_line_hint) as mock_direct_call:
        # The above patches ensure that whether func_replacer uses the dispatch map
        # or calls extract_python_block_ast directly, our mock is used.
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--line", "3", "--yes"], capsys)

    assert code == 0, f"[LINE HINT] Exit:{code}, Err:{err}, Out:{out}" # <<< VERIFY
    # Check if either of the patched methods was called (depending on func_replacer's internal logic)
    called_correctly = False
    if mock_direct_call.called:
        call_args, call_kwargs = mock_direct_call.call_args
        if call_kwargs.get('target_line_1idx') == 3 and call_kwargs.get('target_entity_name') == "old_function_name":
            called_correctly = True
    # (Checking calls to dispatch map is more complex if needed)
    assert called_correctly, "Mocked Python extractor was not called with expected line/name arguments."
    assert f"Successfully replaced 'old_function_name'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "Replaced content" in updated_content

def test_target_entity_not_found(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    with patch('func_replacer.rgc_lib.extract_python_block_ast', return_value=(None, -1, -1)):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "non_existent_func", "--yes"], capsys)
    assert code == 1; assert "Error: Could not find or extract" in err; assert "non_existent_func" in err

def test_confirmation_prompt_no(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)
    def mock_py_extractor(*args, **kwargs):
        if kwargs.get('target_entity_name') == "old_function_name": return PYTHON_TARGET_CONTENT_ORIGINAL.splitlines(True)[2:6], 2, 5
        return None, -1, -1
    with patch('builtins.input', return_value='n'), \
         patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name"], capsys)
    assert code == 0; assert "Replacement aborted by user." in out
    original_content_norm = PYTHON_TARGET_CONTENT_ORIGINAL.replace('\r\n', '\n')
    assert open(temp_target_file, encoding='utf-8').read().replace('\r\n', '\n') == original_content_norm

def test_replace_ruby_method_by_name(mock_clipboard, temp_target_file, capsys):
    mock_clipboard(NEW_RUBY_METHOD_CLIPBOARD)
    ruby_target_path = temp_target_file.replace(".py", ".rb")
    target_lines_local = RUBY_TARGET_CONTENT_ORIGINAL.splitlines(True)
    with open(ruby_target_path, 'w', encoding='utf-8') as f: f.write(RUBY_TARGET_CONTENT_ORIGINAL)
    def mock_ruby_extractor(lines_arg, target_line_0idx_arg, target_entity_name=None): # <<< Corrected signature
        if target_entity_name == "method_to_replace": return target_lines_local[2:5], 2, 4
        return None, -1, -1
    # Patch where used
    with patch('func_replacer.rgc_lib.EXTRACTOR_DISPATCH_MAP', {"ruby": mock_ruby_extractor, **rgc_lib.EXTRACTOR_DISPATCH_MAP}):
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
    def mock_py_extractor(*args, **kwargs):
        if kwargs.get('target_entity_name') == "old_function_name": return PYTHON_TARGET_CONTENT_ORIGINAL.splitlines(True)[2:6], 2, 5
        return None, -1, -1
    with patch('func_replacer.shutil.copy2') as mock_copy, \
         patch('func_replacer.rgc_lib.extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--yes", "--backup"], capsys)
    assert code == 0; mock_copy.assert_called_once_with(str(temp_target_file), backup_file_path); assert "Backup created:" in out
    if os.path.exists(backup_file_path): os.unlink(backup_file_path)
