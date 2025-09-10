# File: json_replacer/tests/json_replacer_test.py

import pytest
import json
from pathlib import Path
from unittest.mock import patch

from json_replacer import json_replacer

@pytest.fixture
def project(tmp_path: Path):
    """Creates a complex temporary project for JSON tests."""
    d = tmp_path / "json_project"
    d.mkdir()
    (d / "config.py").write_text(
        "# Line 1: Settings\n"
        "class Settings:\n"
        "    # Line 3: Timeout\n"
        "    TIMEOUT = 30\n"
        "    # Line 5: End of class\n",
        encoding="utf-8"
    )
    (d / "app.py").write_text(
        "import config\n\n"
        "def run():\n"
        "    s = config.Settings()\n"
        "    print(f'Timeout is {s.TIMEOUT}')\n",
        encoding="utf-8"
    )
    with patch('pathlib.Path.cwd', return_value=d):
        yield d

# --- Full Workflow and Edge Case Tests ---

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_scenario_multi_file_edits(mock_confirm, project):
    config_py = project / "config.py"
    app_py = project / "app.py"
    ops = [
      {"file_path": str(config_py), "operation": "replace_block", "locator": {"type": "line_number", "value": "4"}, "content": "    TIMEOUT = 9000"},
      {"file_path": str(config_py), "operation": "insert_after", "locator": {"type": "block_content", "value": "    TIMEOUT = 9000\n"}, "content": "    RETRIES = 5"},
      {"file_path": str(app_py), "operation": "replace_block", "locator": {"type": "block_content", "value": "print(f'Timeout is {s.TIMEOUT}')"}, "content": "    print(f'Timeout is {s.TIMEOUT} and retries are {s.RETRIES}')"}
    ]
    json_replacer.preview_and_apply_json(ops, False, False)
    config_content = config_py.read_text()
    assert "TIMEOUT = 30" not in config_content
    assert "    TIMEOUT = 9000\n" in config_content
    assert "    RETRIES = 5\n" in config_content
    app_content = app_py.read_text()
    assert "retries are {s.RETRIES}" in app_content

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_scenario_multiple_edits_on_same_file(mock_confirm, project):
    config_py = project / "config.py"
    ops = [
        {"file_path": str(config_py), "operation": "replace_block", "locator": {"type": "line_number", "value": "2"}, "content": "class BetterSettings:"},
        {"file_path": str(config_py), "operation": "insert_after", "locator": {"type": "block_content", "value": "class BetterSettings:\n"}, "content": "    # Class-level docstring"},
    ]
    json_replacer.preview_and_apply_json(ops, False, False)
    content = config_py.read_text()
    assert "class Settings:" not in content
    assert "class BetterSettings:\n    # Class-level docstring" in content

def test_error_on_edit_nonexistent_file(project, capsys):
    ops = [{"file_path": "no.py", "operation": "replace_block", "locator": {"type": "line_number", "value": "1"}}]
    json_replacer.preview_and_apply_json(ops, False, True)
    captured = capsys.readouterr()
    assert "Cannot edit 'no.py' because it does not exist" in captured.out

def test_error_on_create_existing_file(project, capsys):
    ops = [{"file_path": "config.py", "operation": "create_file", "content": "..."}]
    json_replacer.preview_and_apply_json(ops, False, True)
    captured = capsys.readouterr()
    assert "Cannot create 'config.py' because it already exists" in captured.out
