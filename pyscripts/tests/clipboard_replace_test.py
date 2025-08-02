# tests/clipboard_replace_test.py
import sys
import pytest
from pathlib import Path
from unittest import mock

mock_cl_utils = mock.MagicMock()
sys.modules['cross_platform.clipboard_utils'] = mock_cl_utils

# Import after sys.modules is patched
import clipboard_replace
from clipboard_replace import extract_function_name, replace_python_block

PY_TEMPLATE = """
def foo():
    print("old")

class Bar:
    pass

def baz():
    pass
"""
NEW_FOO = """def foo():
    print("new line 1")
    print("new line 2")"""
NEW_BAR_CLASS = """class Bar:
    def __init__(self, x):
        self.x = x
    def get_x(self):
        return self.x"""

PY_FILE_WITH_DECORATOR_ABOVE_FOO = """
@decorator_one
@decorator_two
def foo():
    print("old foo in decorated file")

class Bar:
    pass
"""
PY_TEMPLATE_FOO_LAST = """
class Bar:
    pass

def foo():
    print("old foo last")
"""

@pytest.fixture
def mock_get_clipboard_cr(monkeypatch):
    mock_get = mock.Mock()
    # Patching get_clipboard on the imported module instance
    monkeypatch.setattr(clipboard_replace, "get_clipboard", mock_get)
    return mock_get

@pytest.fixture
def mock_console_stdout_print_cr(monkeypatch):
    mock_print = mock.Mock()
    monkeypatch.setattr(clipboard_replace.console_stdout, "print", mock_print)
    return mock_print

@pytest.fixture
def cr_runner(monkeypatch):
    # This runner now directly calls the main function for better control and mocking.
    def execute_script_function(file_path_str, no_stats):
        # Args are parsed by the test, then passed to the function
        clipboard_replace.run_clipboard_replace(file_path_str, no_stats)
    return execute_script_function


def test_extract_function_name_success():
    assert extract_function_name("   def  my_func(x):") == "my_func"
    assert extract_function_name("class MyClass:") == "MyClass"

def test_extract_function_name_empty_input(capsys):
    with pytest.raises(SystemExit) as e:
        extract_function_name("")
    assert e.value.code == 1
    # Normalize stderr output for assertion (handles Rich styling)
    captured_err = " ".join(capsys.readouterr().err.split())
    assert "does not appear to be a Python def/class" in captured_err

def test_extract_function_name_failure(capsys):
    with pytest.raises(SystemExit) as e:
        extract_function_name("not a function")
    assert e.value.code == 1
    captured_err = " ".join(capsys.readouterr().err.split())
    assert "does not appear to be a Python def/class" in captured_err

def test_replace_python_block_replaces_correct_block():
    original = PY_TEMPLATE.lstrip().splitlines(True)
    updated, _ = replace_python_block(original, "foo", NEW_FOO)
    text = "".join(updated)
    assert "print(\"new line 1\")" in text
    assert "print(\"old\")" not in text

def test_replace_no_such_function(capsys):
    lines = PY_TEMPLATE.lstrip().splitlines(True)
    with pytest.raises(SystemExit) as e:
        replace_python_block(lines, "does_not_exist", NEW_FOO)
    assert e.value.code == 1
    captured_err = " ".join(capsys.readouterr().err.split())
    assert "Function/class 'does_not_exist' not found" in captured_err

def test_replace_multiple_defs(capsys):
    multiline = "def foo(): pass\ndef foo(): pass\n"
    lines = multiline.lstrip().splitlines(True)
    with pytest.raises(SystemExit) as e:
        replace_python_block(lines, "foo", NEW_FOO)
    assert e.value.code == 1
    captured_err = " ".join(capsys.readouterr().err.split())
    assert "Multiple definitions of 'foo' found" in captured_err

def test_replace_python_block_replaces_class():
    original = PY_TEMPLATE.lstrip().splitlines(True)
    updated_lines, _ = replace_python_block(original, "Bar", NEW_BAR_CLASS)
    text = "".join(updated_lines)
    assert "def __init__(self, x):" in text
    assert "class Bar:\n    pass" not in text # Original class content

def test_replace_block_in_file_with_decorators():
    original_lines = PY_FILE_WITH_DECORATOR_ABOVE_FOO.lstrip().splitlines(True)
    updated_lines, _ = replace_python_block(original_lines, "foo", NEW_FOO)
    text = "".join(updated_lines)
    # The NEW_FOO does not have decorators, so old ones should be gone.
    # This tests that the replacement correctly identifies the start_idx above decorators.
    assert "@decorator_one" not in text
    assert "print(\"new line 1\")" in text
    assert "print(\"old foo in decorated file\")" not in text

def test_replace_python_block_foo_is_last():
    content = PY_TEMPLATE_FOO_LAST.lstrip()
    if not content.endswith("\n"): content += "\n"
    original = content.splitlines(True)
    updated, _ = replace_python_block(original, "foo", NEW_FOO)
    text = "".join(updated)
    assert "print(\"new line 1\")" in text
    # The NEW_FOO itself ends with "print("new line 2")", and it gets a newline added by splitlines(True) logic in replace_python_block
    assert text.endswith("print(\"new line 2\")\n")


def test_main_end_to_end(mock_get_clipboard_cr, tmp_path, cr_runner, mock_console_stdout_print_cr):
    p = tmp_path / "t.py"
    p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")
    mock_get_clipboard_cr.return_value = NEW_FOO

    with pytest.raises(SystemExit) as e:
        # Call the main logic function directly via the modified runner
        cr_runner(str(p), True) # True for no_stats
    assert e.value.code == 0

    # Check that console_stdout.print was called with the success message
    # The script prints: f"Replaced '{func_name_to_replace}' successfully in '{file_path_obj}'."
    # func_name_to_replace will be 'foo'
    # file_path_obj will be p
    expected_message = f"Replaced 'foo' successfully in '{str(p)}'."
    
    # Check if any call to the mock has the expected message
    # Rich might pass additional styling arguments, so we check the first positional arg.
    called_with_expected_message = False
    for call_args_list in mock_console_stdout_print_cr.call_args_list:
        args, kwargs = call_args_list
        if args and args[0] == expected_message:
            called_with_expected_message = True
            break
    assert called_with_expected_message, f"Expected print call with '{expected_message}' not found."
    
    assert p.read_text(encoding="utf-8").count("print(\"new line 1\")") == 1


def test_main_incorrect_args(capsys, monkeypatch):
    # Test arg parsing failure by attempting to run __main__ block
    # This requires restoring sys.argv and calling the script's main entry point.
    # The cr_runner fixture was changed to call the function directly, so this test needs adjustment.
    # We'll test the parser directly.
    with pytest.raises(SystemExit) as e:
        clipboard_replace.parser_cr.parse_args([]) # No arguments
    assert e.value.code == 2
    # argparse prints to stderr by default
    assert "the following arguments are required: file" in capsys.readouterr().err

def test_main_extract_function_name_fails(mock_get_clipboard_cr, tmp_path, capsys, cr_runner):
    p = tmp_path / "t.py"; p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")
    mock_get_clipboard_cr.return_value = "this is not a function"
    with pytest.raises(SystemExit) as e:
        cr_runner(str(p), True) # True for no_stats
    assert e.value.code == 1
    captured_err = " ".join(capsys.readouterr().err.split())
    assert "does not appear to be a Python def/class" in captured_err

def test_main_function_not_found_in_file(mock_get_clipboard_cr, tmp_path, capsys, cr_runner):
    p = tmp_path / "f.py"; p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")
    mock_get_clipboard_cr.return_value = "def non_existent_func(): pass"
    with pytest.raises(SystemExit) as e:
        cr_runner(str(p), True) # True for no_stats
    assert e.value.code == 1
    captured_err = " ".join(capsys.readouterr().err.split())
    assert "Function/class 'non_existent_func' not found" in captured_err

def test_main_input_file_not_found(mock_get_clipboard_cr, capsys, cr_runner):
    mock_get_clipboard_cr.return_value = NEW_FOO
    with pytest.raises(SystemExit) as e:
        cr_runner("non_existent_file.py", True) # True for no_stats
    assert e.value.code == 1
    captured_err = " ".join(capsys.readouterr().err.split())
    assert "Error: File 'non_existent_file.py' not found" in captured_err

def test_main_multiple_definitions_in_file(mock_get_clipboard_cr, tmp_path, capsys, cr_runner):
    p = tmp_path / "f_multi.py"; p.write_text("def foo(): pass\ndef foo(): pass\n", encoding="utf-8")
    mock_get_clipboard_cr.return_value = NEW_FOO # Tries to replace 'foo'
    with pytest.raises(SystemExit) as e:
        cr_runner(str(p), True) # True for no_stats
    assert e.value.code == 1
    captured_err = " ".join(capsys.readouterr().err.split())
    assert "Multiple definitions of 'foo' found" in captured_err
