# tests/test_func_replacer.py
import pytest
from unittest.mock import patch, MagicMock
import sys
import os
import tempfile
import re # Needed for checking output

# Adjust import based on actual location if needed
# Assuming func_replacer.py is in the parent directory relative to tests/
# or that the project root is in PYTHONPATH when running pytest
import func_replacer
import rgcodeblock_lib as rgc_lib

# We also need access to the *dummy* get_clipboard or mock it
try:
    # Try importing the real one first
    from cross_platform.clipboard_utils import get_clipboard
except ImportError:
    # Define a dummy if the real one isn't importable in the test env
    # Use a known global variable within the test module to control its return value
    MOCK_CLIPBOARD_CONTENT_FOR_DUMMY = ""
    def get_clipboard():
        print("Warning: Using dummy get_clipboard for test.", file=sys.stderr)
        return MOCK_CLIPBOARD_CONTENT_FOR_DUMMY
    # If func_replacer already imported the potentially failing one, patch it
    if hasattr(func_replacer, 'get_clipboard'):
        func_replacer.get_clipboard = get_clipboard


# Global variable used by the dummy clipboard if needed, or patched by fixture
MOCK_CLIPBOARD_CONTENT = ""

@pytest.fixture
def mock_clipboard(monkeypatch):
    """Fixture to manage the global MOCK_CLIPBOARD_CONTENT and patch get_clipboard"""
    global MOCK_CLIPBOARD_CONTENT
    # Reset before each test using this fixture
    MOCK_CLIPBOARD_CONTENT = ""

    # Define the mock function that reads the global
    def mock_get_clipboard_func():
        return MOCK_CLIPBOARD_CONTENT

    # Patch the get_clipboard function *within the func_replacer module* where it's used
    monkeypatch.setattr(func_replacer, 'get_clipboard', mock_get_clipboard_func)

    # Provide a function to the test to set the clipboard content easily
    def set_clipboard_content(content):
        global MOCK_CLIPBOARD_CONTENT
        MOCK_CLIPBOARD_CONTENT = content
    return set_clipboard_content


@pytest.fixture
def temp_target_file():
    """Creates a temporary file for testing replacements."""
    tf = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".py", encoding='utf-8')
    tf.close() # Close (needed on some OSes) so the script can open it
    yield tf.name # Provide the path to the test
    if os.path.exists(tf.name): # Ensure cleanup happens even if test fails
        os.unlink(tf.name)

# Helper function to run main (CORRECTED to assume exit code 0 on normal completion)
def run_func_replacer(args_list, capsys):
    """Helper to run the script's main() with mocked sys.argv and capture output."""
    # Ensure library notes are clear for each test run
    if hasattr(rgc_lib, 'OPTIONAL_LIBRARY_NOTES'):
        rgc_lib.OPTIONAL_LIBRARY_NOTES.clear()

    with patch.object(sys, 'argv', ['func_replacer.py'] + args_list):
        exit_code = None # Default to None
        try:
            func_replacer.main()
            # If main completes without SystemExit, assume success (code 0)
            exit_code = 0 # <<< CORRECTED: Assume 0 if no exception/SystemExit
        except SystemExit as e:
            exit_code = e.code # Capture explicit exit code
        # Let other unexpected exceptions propagate to fail the test
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
""" # Line 11 (0-idx: 10) is blank

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
    """Test replacing a Python function by name using clipboard content."""
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)

    # Mock the library's extractor to correctly find 'old_function_name'
    # Needs to return (block_lines, start_0idx, end_0idx)
    def mock_py_extractor(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name":
            # Original block is lines 3-6 (0-indexed: 2-5)
            return lines[2:6], 2, 5
        return None, -1, -1

    with patch.object(rgc_lib, 'extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--yes"], capsys)

    assert code == 0, f"Expected exit code 0, got {code}. Output:\n{out}\nError:\n{err}"
    assert f"Successfully replaced 'old_function_name' in '{temp_target_file}'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "def old_function_name(new_param):" in updated_content
    assert "Replaced content" in updated_content
    assert "old stuff" not in updated_content # Check old content removed
    assert "class AnotherClass:" in updated_content # Check other content remains

def test_replace_infer_name_from_clipboard(mock_clipboard, temp_target_file, capsys):
    """Test replacing based on name inferred from clipboard."""
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_WITH_NEW_NAME) # Contains "class NewShinyClass"

    # Target needs the name 'NewShinyClass' to be replaced. Create valid target content.
    target_content_for_test = """
# Target file for infer name test
class NewShinyClass: # Line 3 (0-idx: 2)
    # Old content to be replaced
    pass # Line 5 (0-idx: 4)

def another_func(): # Line 7 (0-idx: 6)
    pass
"""
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(target_content_for_test)

    # Mock extractor to find the existing 'NewShinyClass'
    def mock_py_extractor_for_new(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "NewShinyClass":
             # Block is lines 3-5 (0-indexed: 2-4)
             return lines[2:5], 2, 4
        return None, -1, -1

    with patch.object(rgc_lib, 'extract_python_block_ast', side_effect=mock_py_extractor_for_new):
        out, err, code = run_func_replacer([str(temp_target_file), "--yes"], capsys) # No --name

    assert code == 0, f"Expected exit code 0, got {code}. Output:\n{out}\nError:\n{err}"
    # Check output for inferred name message
    # Using regex because ANSI codes might be present if colors are on by default
    assert re.search(r"Inferred entity name to replace: 'NewShinyClass'", out)
    assert f"Successfully replaced 'NewShinyClass' in '{temp_target_file}'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "class NewShinyClass:" in updated_content # Should now be the one from clipboard
    assert "'''A new class'''" in updated_content
    assert "pass # Line 5" not in updated_content # Original content replaced
    assert "def another_func():" in updated_content # Other parts remain

def test_replace_using_source_file(mock_clipboard, temp_target_file, capsys):
    """Test replacement using --source-file instead of clipboard."""
    # Set clipboard to something different to ensure it's not used
    mock_clipboard("THIS SHOULD NOT BE USED")

    # Create a source file with the new content
    source_tf = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".py", encoding='utf-8')
    source_tf.write(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    source_tf.close()

    # Prepare target file
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)

    # Mock the extractor as in the first test
    def mock_py_extractor(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name": return lines[2:6], 2, 5
        return None, -1, -1

    with patch.object(rgc_lib, 'extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([
            str(temp_target_file),
            "--name", "old_function_name",
            "--source-file", source_tf.name,
            "--yes"
        ], capsys)

    os.unlink(source_tf.name) # Clean up source temp file

    assert code == 0
    assert f"Successfully replaced 'old_function_name' in '{temp_target_file}'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "Replaced content" in updated_content # Content from source file used
    assert "THIS SHOULD NOT BE USED" not in updated_content

def test_replace_using_line_hint(mock_clipboard, temp_target_file, capsys):
    """Test pinpointing the function using --line."""
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)

    # Explicit side effect function for the mock
    def mock_py_extractor_for_line_hint(lines, content, target_entity_name=None, target_line_1idx=None):
        # Simulate finding based on line hint AND name check
        if target_entity_name == "old_function_name" and target_line_1idx == 3:
             # Return the expected block (lines 3-6, 0-indexed 2-5)
             return lines[2:6], 2, 5
        return None, -1, -1

    # Use the side_effect with MagicMock or directly
    mock_obj = MagicMock(side_effect=mock_py_extractor_for_line_hint)

    with patch.object(rgc_lib, 'extract_python_block_ast', mock_obj):
         out, err, code = run_func_replacer([
             str(temp_target_file),
             "--name", "old_function_name", # Name is still useful for confirmation inside extractor
             "--line", "3", # 1-based line number where 'def old_function_name' starts
             "--yes"
         ], capsys)

    assert code == 0, f"Expected exit code 0, got {code}. Output:\n{out}\nError:\n{err}"

    # Assert call args on the original MagicMock object
    mock_obj.assert_called_once()
    call_args, call_kwargs = mock_obj.call_args
    # Check specific kwargs used in the call
    assert call_kwargs.get('target_line_1idx') == 3
    assert call_kwargs.get('target_entity_name') == "old_function_name"

    assert f"Successfully replaced 'old_function_name' in '{temp_target_file}'" in out
    updated_content = open(temp_target_file, encoding='utf-8').read()
    assert "Replaced content" in updated_content


def test_target_entity_not_found(mock_clipboard, temp_target_file, capsys):
    """Test error handling when the target function/class is not found."""
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME) # Content irrelevant here
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)

    # Mock extractor explicitly returns None (not found)
    with patch.object(rgc_lib, 'extract_python_block_ast', return_value=(None, -1, -1)):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "non_existent_func", "--yes"], capsys)

    assert code == 1 # Expect non-zero exit code for failure
    assert "Error: Could not find or extract" in err
    assert "non_existent_func" in err

def test_confirmation_prompt_no(mock_clipboard, temp_target_file, capsys):
    """Test user aborting via confirmation prompt."""
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(PYTHON_TARGET_CONTENT_ORIGINAL)

    def mock_py_extractor(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name": return lines[2:6], 2, 5
        return None, -1, -1

    # Simulate user typing 'n' then Enter
    with patch('builtins.input', return_value='n'), \
         patch.object(rgc_lib, 'extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name"], capsys) # No --yes

    assert code == 0 # Aborting is considered a "successful" exit (code 0)
    # Check that the prompt output was shown
    assert "Replace 'old_function_name'" in out # Part of the prompt question
    assert "--- Current Block ---" in out
    assert "--- New Block ---" in out
    # Check for the abortion message
    assert "Replacement aborted by user." in out
    # Verify file was NOT changed
    original_content = PYTHON_TARGET_CONTENT_ORIGINAL
    # Normalize newlines just in case test env differs from source string
    assert open(temp_target_file, encoding='utf-8').read().replace('\r\n', '\n') == original_content.replace('\r\n', '\n')

def test_replace_ruby_method_by_name(mock_clipboard, temp_target_file, capsys):
    """Test replacing a Ruby method."""
    mock_clipboard(NEW_RUBY_METHOD_CLIPBOARD)

    # Create a temporary ruby file
    ruby_target_path = temp_target_file.replace(".py", ".rb")
    with open(ruby_target_path, 'w', encoding='utf-8') as f: f.write(RUBY_TARGET_CONTENT_ORIGINAL)

    # Mock the Ruby extractor from the library
    def mock_ruby_extractor(lines, target_line_idx, target_name=None): # Adjust signature if needed
        # Function needs to find block containing target_name="method_to_replace"
        # Let's assume it finds lines 3-5 (0-indexed 2-4)
        if target_name == "method_to_replace":
             return lines[2:5], 2, 4 # Return block, start_0idx, end_0idx
        return None, -1, -1

    with patch.object(rgc_lib, 'extract_ruby_block', side_effect=mock_ruby_extractor):
         out, err, code = run_func_replacer([ruby_target_path, "--name", "method_to_replace", "--yes"], capsys)

    assert code == 0, f"Failed with code {code}. Err: {err}"
    assert f"Successfully replaced 'method_to_replace' in '{ruby_target_path}'" in out
    updated_content = open(ruby_target_path, encoding='utf-8').read()
    assert "Replacement says:" in updated_content
    assert "Original method:" not in updated_content
    assert "other_method" in updated_content # Other parts remain

    os.unlink(ruby_target_path) # Clean up the renamed temp file

def test_backup_flag(mock_clipboard, temp_target_file, capsys):
    """Test that --backup creates a backup file."""
    mock_clipboard(NEW_FUNC_FROM_CLIPBOARD_FOR_OLD_NAME)
    original_content = PYTHON_TARGET_CONTENT_ORIGINAL
    with open(temp_target_file, 'w', encoding='utf-8') as f: f.write(original_content)

    backup_file_path = temp_target_file + ".bak"
    if os.path.exists(backup_file_path): os.unlink(backup_file_path) # Ensure no pre-existing backup

    def mock_py_extractor(lines, content, target_entity_name=None, target_line_1idx=None):
        if target_entity_name == "old_function_name": return lines[2:6], 2, 5
        return None, -1, -1

    with patch.object(rgc_lib, 'extract_python_block_ast', side_effect=mock_py_extractor):
        out, err, code = run_func_replacer([str(temp_target_file), "--name", "old_function_name", "--yes", "--backup"], capsys)

    assert code == 0
    assert os.path.exists(backup_file_path), "Backup file was not created"
    # Verify backup content matches original
    assert open(backup_file_path, encoding='utf-8').read().replace('\r\n', '\n') == original_content.replace('\r\n', '\n')
    # Verify target file was modified
    assert open(temp_target_file, encoding='utf-8').read() != original_content

    os.unlink(backup_file_path) # Clean up backup
