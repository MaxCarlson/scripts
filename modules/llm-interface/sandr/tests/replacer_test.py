# File: sandr/tests/replacer_test.py

import pytest
from pathlib import Path
from unittest.mock import patch

from sandr import replacer

# --- Test Fixtures ---

@pytest.fixture
def project(tmp_path: Path):
    """Creates a complex temporary project directory for robust testing."""
    d = tmp_path / "project"
    d.mkdir()
    
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text(
        "import os\n\n"
        "from utils.helpers import helper_one\n\n"
        "def main():\n"
        "    print('Hello, world!')\n"
        "    helper_one()\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8"
    )
    
    (d / "src" / "utils").mkdir()
    (d / "src" / "utils" / "helpers.py").write_text(
        "# Utility functions\n\n"
        "def helper_one():\n"
        "    # A simple helper\n"
        "    return 1\n\n"
        "def helper_two():\n"
        "    # Another helper\n"
        "    return 2\n",
        encoding="utf-8"
    )

    (d / "README.md").write_text(
        "# My Project\n\n"
        "This is the readme.\n",
        encoding="utf-8"
    )
    
    # Run tests from within this directory
    with patch('pathlib.Path.cwd', return_value=d):
        yield d

# --- Parsing Logic Tests ---

def test_parse_empty_and_whitespace_clipboard():
    assert replacer.parse_clipboard_content("") == []
    assert replacer.parse_clipboard_content("  \n\t  ") == []

def test_parse_delete_operation_passes():
    clipboard = (
        "[START_FILE_EDIT: src/main.py]\n"
        "<<<<<<< SEARCH\n"
        "    print('Hello, world!')\n"
        "=======\n"
        ">>>>>>> REPLACE\n"
        "[END_FILE]"
    )
    ops = replacer.parse_clipboard_content(clipboard)
    assert len(ops) == 1
    assert ops[0]["type"] == "replace"
    assert ops[0]["replace"] == ""

def test_parse_complex_multiline_search_and_replace():
    clipboard = (
        "[START_FILE_EDIT: src/main.py]\n"
        "<<<<<<< SEARCH\n"
        "def main():\n"
        "    print('Hello, world!')\n"
        "    helper_one()\n"
        "=======\n"
        "def main():\n"
        "    # Refactored\n"
        "    print('Hello, new world!')\n"
        ">>>>>>> REPLACE\n"
        "[END_FILE]"
    )
    ops = replacer.parse_clipboard_content(clipboard)
    assert len(ops) == 1
    assert ops[0]['search'] == "def main():\n    print('Hello, world!')\n    helper_one()"

def test_parse_malformed_clipboard_gracefully_fails():
    # Missing [END_FILE]
    clipboard1 = "[START_FILE_CREATE: new.py]\ncontent"
    assert replacer.parse_clipboard_content(clipboard1) == []
    
    # Mismatched delimiters
    clipboard2 = "[START_FILE_EDIT: a.py]\n<<<<<<< SEARCH\ncontent\n=======\n>>>>>>> ANCHOR\n[END_FILE]"
    assert replacer.parse_clipboard_content(clipboard2) == []

    # No file block
    clipboard3 = "<<<<<<< SEARCH\ncontent\n=======\nreplace\n>>>>>>> REPLACE"
    assert replacer.parse_clipboard_content(clipboard3) == []

# --- Full Workflow and Edge Case Tests ---

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_scenario_create_and_multi_edit(mock_confirm, project):
    """Comprehensive test: create one file, edit two others."""
    new_file_path = project / "docs" / "guide.md"
    main_py_path = project / "src" / "main.py"
    helpers_py_path = project / "src" / "utils" / "helpers.py"

    clipboard = (
        f"[START_FILE_CREATE: {new_file_path}]\n"
        "# New Guide\n"
        "How to use this project.\n"
        "[END_FILE]\n"
        f"[START_FILE_EDIT: {main_py_path}]\n"
        "<<<<<<< INSERT\n"
        "from utils.helpers import helper_two\n"
        "=======\n"
        "AFTER\n"
        "<<<<<<< ANCHOR\n"
        "from utils.helpers import helper_one\n"
        ">>>>>>> ANCHOR\n"
        "<<<<<<< SEARCH\n"
        "    helper_one()\n"
        "=======\n"
        "    helper_one()\n"
        "    helper_two()\n"
        ">>>>>>> REPLACE\n"
        "[END_FILE]\n"
        f"[START_FILE_EDIT: {helpers_py_path}]\n"
        "<<<<<<< SEARCH\n"
        "def helper_two():\n"
        "    # Another helper\n"
        "    return 2\n"
        "=======\n"
        ">>>>>>> REPLACE\n"
        "[END_FILE]"
    )
    
    ops = replacer.parse_clipboard_content(clipboard)
    assert len(ops) == 4

    assert not new_file_path.exists()
    
    replacer.preview_and_apply_changes(ops, dry_run=False, auto_confirm=False)
    
    # Verify creation
    assert new_file_path.exists()
    assert "How to use this project" in new_file_path.read_text()
    
    # Verify edits to main.py
    main_content = main_py_path.read_text()
    assert "from utils.helpers import helper_two" in main_content
    assert "helper_two()" in main_content

    # Verify deletion in helpers.py
    helpers_content = helpers_py_path.read_text()
    assert "def helper_two()" not in helpers_content

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_apply_edit_error_if_anchor_not_found(mock_confirm, project, capsys):
    main_py_path = project / "src" / "main.py"
    ops = [{
        "type": "replace",
        "path": main_py_path,
        "search": "non_existent_string_in_file",
        "replace": "b"
    }]
    
    replacer.preview_and_apply_changes(ops, dry_run=False, auto_confirm=False)
    captured = capsys.readouterr()
    assert "ERROR REPLACE" in captured.out
    assert "SEARCH block not found" in captured.out

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_apply_edit_error_if_anchor_not_unique(mock_confirm, project, capsys):
    main_py = project / "src" / "main.py"
    # Make a non-unique string by adding another call
    content = main_py.read_text()
    main_py.write_text(content.replace("main()", "main()\n    main()"), encoding="utf-8")
    
    ops = [{
        "type": "insert",
        "path": main_py,
        "content": "# insert",
        "position": "after",
        "anchor": "main()"
    }]
    
    replacer.preview_and_apply_changes(ops, dry_run=False, auto_confirm=False)
    captured = capsys.readouterr()
    assert "ERROR INSERT" in captured.out
    assert "is not unique" in captured.out
    assert "(2 occurrences)" in captured.out

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_edit_empty_file(mock_confirm, project):
    empty_file = project / "empty.txt"
    empty_file.touch()

    ops = [{
        "type": "insert",
        "path": empty_file,
        "content": "First line",
        "position": "after",
        "anchor": "" # Insert relative to empty content
    }]

    # This should fail because anchor is not unique
    replacer.preview_and_apply_changes(ops, dry_run=False, auto_confirm=False)
    assert empty_file.read_text() == ""

    # A better way is to replace the empty content
    ops = [{"type": "replace", "path": empty_file, "search": "", "replace": "First line"}]
    replacer.preview_and_apply_changes(ops, dry_run=False, auto_confirm=False)
    assert empty_file.read_text() == "First line"
