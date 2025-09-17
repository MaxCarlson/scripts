# File: json_replacer/tests/json_replacer_corner_cases_test.py

import pytest
import json
from pathlib import Path
from unittest.mock import patch

from json_replacer import json_replacer

@pytest.fixture
def corner_case_project(tmp_path: Path):
    d = tmp_path / "cc_project"
    d.mkdir()
    (d / "config.yml").write_text(
        "version: 2\n"
        "services:\n"
        "  db:\n"
        "    image: postgres\n",
        encoding="utf-8"
    )
    with patch('pathlib.Path.cwd', return_value=d):
        yield d

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_create_file_in_deeply_nested_new_directory(mock_confirm, corner_case_project):
    new_file = corner_case_project / "a" / "b" / "c" / "d" / "deep_file.txt"
    ops = [{
        "file_path": str(new_file),
        "operation": "create_file",
        "content": "Deeply nested file."
    }]
    
    assert not new_file.exists()
    json_replacer.preview_and_apply_json(ops, False, True)
    assert new_file.exists()
    assert new_file.read_text() == "Deeply nested file."

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_create_file_and_immediately_edit_it_json(mock_confirm, corner_case_project):
    new_file = corner_case_project / "flow.py"
    ops = [
        {"file_path": str(new_file), "operation": "create_file", "content": "def main():\n    pass\n"},
        {"file_path": str(new_file), "operation": "insert_before", "locator": {"type": "block_content", "value": "def main():\n"}, "content": "# Main entrypoint"}
    ]
    
    json_replacer.preview_and_apply_json(ops, False, True)
    
    assert new_file.exists()
    content = new_file.read_text()
    assert content.strip() == "# Main entrypoint\ndef main():\n    pass"

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_delete_all_content_from_file(mock_confirm, corner_case_project):
    config_yml = corner_case_project / "config.yml"
    original_content = config_yml.read_text()
    
    ops = [{"file_path": str(config_yml), "operation": "delete_block", "locator": {"type": "block_content", "value": original_content}}]
    
    json_replacer.preview_and_apply_json(ops, False, True)
    assert config_yml.read_text() == ""

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_delete_block_without_content_field(mock_confirm, corner_case_project):
    config_yml = corner_case_project / "config.yml"
    ops = [{"file_path": str(config_yml), "operation": "delete_block", "locator": {"type": "line_number", "value": "1"}}]
    
    json_replacer.preview_and_apply_json(ops, False, True)
    
    content = config_yml.read_text()
    assert "version: 2" not in content
    assert "services:" in content
