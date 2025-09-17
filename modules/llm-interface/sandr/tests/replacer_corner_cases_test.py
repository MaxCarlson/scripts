# File: sandr/tests/replacer_corner_cases_test.py

import pytest
from pathlib import Path
from unittest.mock import patch

from sandr import replacer

@pytest.fixture
def corner_case_project(tmp_path: Path):
    d = tmp_path / "cc_project"
    d.mkdir()
    (d / "file_with_no_newline.txt").write_text("line one", encoding="utf-8")
    (d / "empty_file.txt").touch()
    (d / "src").mkdir()
    (d / "src" / "app.py").write_text(
        "# BEGIN\n\n"
        "def start():\n"
        "    pass\n\n"
        "# END\n",
        encoding="utf-8"
    )
    with patch('pathlib.Path.cwd', return_value=d):
        yield d

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_create_file_and_immediately_edit_it(mock_confirm, corner_case_project):
    new_file = corner_case_project / "new_flow.py"
    clipboard = (
        f"[START_FILE_CREATE: {new_file}]\n"
        "def initial_function():\n"
        "    # Step 1\n"
        "    pass\n"
        "[END_FILE]\n"
        f"[START_FILE_EDIT: {new_file}]\n"
        "<<<<<<< INSERT\n"
        "# A header comment\n"
        "import os\n"
        "=======\n"
        "BEFORE\n"
        "<<<<<<< ANCHOR\n"
        "def initial_function():\n"
        ">>>>>>> ANCHOR\n"
        "[END_FILE]"
    )
    ops = replacer.parse_clipboard_content(clipboard)
    assert len(ops) == 2

    replacer.preview_and_apply_changes(ops, False, True)

    assert new_file.exists()
    content = new_file.read_text()
    assert "# A header comment" in content
    assert "import os" in content
    assert "def initial_function" in content

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_replace_entire_file_content(mock_confirm, corner_case_project):
    app_py = corner_case_project / "src" / "app.py"
    original_content = app_py.read_text()
    new_content = "# Rewritten from scratch\n\nprint('hello')\n"
    clipboard = (
        f"[START_FILE_EDIT: {app_py}]\n"
        f"<<<<<<< SEARCH\n"
        f"{original_content}"
        f"=======\n"
        f"{new_content}"
        f">>>>>>> REPLACE\n"
        f"[END_FILE]"
    )
    ops = replacer.parse_clipboard_content(clipboard)
    replacer.preview_and_apply_changes(ops, False, True)
    assert app_py.read_text() == new_content

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_insert_at_very_beginning_of_file(mock_confirm, corner_case_project):
    app_py = corner_case_project / "src" / "app.py"
    clipboard = (
        f"[START_FILE_EDIT: {app_py}]\n"
        f"<<<<<<< INSERT\n"
        f"# Start of file comment\n"
        f"=======\n"
        f"BEFORE\n"
        f"<<<<<<< ANCHOR\n"
        f"# BEGIN\n"
        f">>>>>>> ANCHOR\n"
        f"[END_FILE]"
    )
    ops = replacer.parse_clipboard_content(clipboard)
    replacer.preview_and_apply_changes(ops, False, True)
    content = app_py.read_text()
    assert content.startswith("# Start of file comment\n")

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_insert_at_very_end_of_file(mock_confirm, corner_case_project):
    app_py = corner_case_project / "src" / "app.py"
    clipboard = (
        f"[START_FILE_EDIT: {app_py}]\n"
        f"<<<<<<< INSERT\n"
        f"# Final comment\n"
        f"=======\n"
        f"AFTER\n"
        f"<<<<<<< ANCHOR\n"
        f"# END\n"
        f">>>>>>> ANCHOR\n"
        f"[END_FILE]"
    )
    ops = replacer.parse_clipboard_content(clipboard)
    replacer.preview_and_apply_changes(ops, False, True)
    content = app_py.read_text()
    assert content.strip().endswith("# Final comment")
