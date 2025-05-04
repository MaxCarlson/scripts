# test_clipboard_replace.py
import sys
import pytest
import tempfile
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
    print("new line 2")"""

def test_extract_function_name_success():
    name = extract_function_name("   def  my_func(x):")
    assert name == "my_func"

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

def test_main_end_to_end(monkeypatch, tmp_path, capsys):
    # prepare a real file
    p = tmp_path / "t.py"
    p.write_text(PY_TEMPLATE.lstrip(), encoding="utf-8")

    # fake clipboard
    monkeypatch.setenv("CLIPBOARD", "ignored")  # if your get_clipboard reads env
    # better monkeypatch get_clipboard() directly:
    import clipboard_replace
    monkeypatch.setattr("clipboard_replace.get_clipboard", lambda: NEW_FOO)

    # run
    monkeypatch.setattr(sys, "argv", ["clipboard_replace.py", str(p)])
    with pytest.raises(SystemExit) as e:
        main()  # if main(sys.exit) is called on error

    # if no exit, capture stdout
    out = capsys.readouterr().out
    assert "Replaced 'foo' successfully" in out

    # verify file content
    text = p.read_text(encoding="utf-8")
    assert "new line 1" in text
    assert "old" not in text
