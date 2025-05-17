#!/usr/bin/env python3
# test_clipboard_replace.py
import sys
import pytest
import clipboard_replace # Import the module to be tested
from pathlib import Path
from clipboard_replace import extract_function_name, replace_python_block, main

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
    print("new line 2")""" # No trailing newline here, handled by split/join

def test_extract_function_name_success():
    name = extract_function_name("   def  my_func(x):")
    assert name == "my_func"

def test_extract_class_name_success():
    name = extract_function_name("class MyClass:")
    assert name == "MyClass"
    name = extract_function_name("  class   My_Other_Class (object) :")
    assert name == "My_Other_Class"

def test_extract_function_name_empty_input():
    with pytest.raises(SystemExit) as e:
        extract_function_name("")
    assert e.value.code == 1

def test_extract_function_name_failure(monkeypatch):
    with pytest.raises(SystemExit) as e:
        extract_function_name("not a function")
    assert e.value.code == 1

def test_replace_python_block_replaces_correct_block(tmp_path):
    p = tmp_path / "f.py"
    p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")
    original = p.read_text(encoding="utf-8").splitlines(True)

    updated = replace_python_block(original, "foo", NEW_FOO)
    text = "".join(updated)
    assert "print(\"new line 1\")" in text
    assert "print(\"old\")" not in text
    assert "class Bar:" in text # Ensure other parts are intact

def test_replace_no_such_function(tmp_path):
    lines = PY_TEMPLATE.lstrip().splitlines(True)
    with pytest.raises(SystemExit) as e:
        replace_python_block(lines, "does_not_exist", NEW_FOO)
    assert e.value.code == 1

def test_replace_multiple_defs(tmp_path):
    multiline = """
def foo(): pass
def foo(): pass
"""
    lines = multiline.lstrip().splitlines(True)
    with pytest.raises(SystemExit) as e:
        replace_python_block(lines, "foo", NEW_FOO)
    assert e.value.code == 1

NEW_BAR_CLASS = """class Bar:
    def __init__(self, x):
        self.x = x
    def get_x(self):
        return self.x"""

def test_replace_python_block_replaces_class(tmp_path):
    p = tmp_path / "f_class.py"
    p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")
    original = p.read_text(encoding="utf-8").splitlines(True)

    updated_lines = replace_python_block(original, "Bar", NEW_BAR_CLASS)
    text = "".join(updated_lines)
    
    assert "def __init__(self, x):" in text  # New Bar content
    assert "def get_x(self):" in text # New Bar content
    # Ensure the old "pass" specific to class Bar is gone.
    # PY_TEMPLATE content for Bar is "class Bar:\n    pass\n"
    assert "class Bar:\n    pass" not in text # Check against exact original block content
    assert "def foo():" in text # Ensure other parts are intact
    assert "def baz():" in text # Ensure other parts are intact

PY_FILE_WITH_DECORATOR_ABOVE_FOO = """
@decorator_one
@decorator_two
def foo():
    print("old foo in decorated file")

class Bar:
    pass
"""

def test_replace_block_in_file_with_decorators(tmp_path):
    p = tmp_path / "f_deco_in_file.py"
    p.write_text(PY_FILE_WITH_DECORATOR_ABOVE_FOO.lstrip(), encoding="utf-8")
    original_lines = p.read_text(encoding="utf-8").splitlines(True)

    # NEW_FOO is "def foo():\n    print(\"new line 1\")\n    print(\"new line 2\")"
    # func_name will be 'foo', new_block is NEW_FOO (which doesn't have decorators)
    updated_lines = replace_python_block(original_lines, "foo", NEW_FOO)
    text = "".join(updated_lines)

    assert "@decorator_one" in text # Decorators should be preserved
    assert "@decorator_two" in text # Decorators should be preserved
    assert "print(\"new line 1\")" in text
    assert "print(\"old foo in decorated file\")" not in text
    assert "class Bar:" in text

PY_TEMPLATE_FOO_LAST = """
class Bar:
    pass

def foo():
    print("old foo last")
"""

def test_replace_python_block_foo_is_last(tmp_path):
    p = tmp_path / "f_foo_last.py"
    content = PY_TEMPLATE_FOO_LAST.lstrip()
    if not content.endswith("\n"):
        content += "\n"
    p.write_text(content, encoding="utf-8")
    original = p.read_text(encoding="utf-8").splitlines(True)

    updated = replace_python_block(original, "foo", NEW_FOO)
    text = "".join(updated)
    assert "print(\"new line 1\")" in text
    assert "print(\"old foo last\")" not in text
    assert "class Bar:" in text
    # NEW_FOO ends with "print(\"new line 2\")". replace_python_block adds newlines.
    assert text.endswith("print(\"new line 2\")\n")

def test_main_end_to_end(monkeypatch, tmp_path, capsys):
    # prepare a real file
    p = tmp_path / "t.py"
    p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")

    # fake clipboard
    monkeypatch.setattr("clipboard_replace.get_clipboard", lambda: NEW_FOO)

    # run
    monkeypatch.setattr(sys, "argv", ["clipboard_replace.py", str(p)])
    main() # Successful run should not SystemExit

    captured = capsys.readouterr()
    assert f"Replaced 'foo' successfully in {str(p)}." in captured.out
    assert captured.err == ""

    # verify file content
    text = p.read_text(encoding="utf-8")
    assert "new line 1" in text
    assert "old" not in text

def test_main_incorrect_args(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["clipboard_replace.py"]) # Not enough args
    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Usage: clipboard_replace.py <file>" in captured.err

    monkeypatch.setattr(sys, "argv", ["clipboard_replace.py", "file1.py", "file2.py"]) # Too many args
    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Usage: clipboard_replace.py <file>" in captured.err

def test_main_extract_function_name_fails(monkeypatch, tmp_path, capsys):
    p = tmp_path / "t.py"
    p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")

    monkeypatch.setattr(clipboard_replace, "get_clipboard", lambda: "this is not a function")
    monkeypatch.setattr(sys, "argv", ["clipboard_replace.py", str(p)])

    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Clipboard content is not a Python def/class. Aborting." in captured.err

def test_main_function_not_found_in_file(monkeypatch, tmp_path, capsys):
    p = tmp_path / "f.py"
    p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")

    monkeypatch.setattr(clipboard_replace, "get_clipboard", lambda: "def non_existent_func(): pass")
    monkeypatch.setattr(sys, "argv", ["clipboard_replace.py", str(p)])

    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Function/class 'non_existent_func' not found. Aborting." in captured.err

def test_main_input_file_not_found(monkeypatch, capsys):
    monkeypatch.setattr(clipboard_replace, "get_clipboard", lambda: NEW_FOO)
    monkeypatch.setattr(sys, "argv", ["clipboard_replace.py", "non_existent_file.py"])

    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "No such file or directory" in captured.err
    assert "non_existent_file.py" in captured.err

def test_main_multiple_definitions_in_file(monkeypatch, tmp_path, capsys):
    p = tmp_path / "f_multi.py"
    multiple_defs_content = "def foo(): pass\ndef Bar(): pass\ndef foo(): pass\n"
    p.write_text(multiple_defs_content)
    
    monkeypatch.setattr(clipboard_replace, "get_clipboard", lambda: NEW_FOO) # NEW_FOO is for 'foo'
    monkeypatch.setattr(sys, "argv", ["clipboard_replace.py", str(p)])

    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Multiple definitions of 'foo' found. Aborting." in captured.err
