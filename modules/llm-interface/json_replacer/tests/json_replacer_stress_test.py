# File: json_replacer/tests/json_replacer_stress_test.py

import pytest
import json
from pathlib import Path
from unittest.mock import patch

from json_replacer import json_replacer

@pytest.fixture
def complex_project(tmp_path: Path):
    """Creates a large, multi-level project for stress testing."""
    root = tmp_path / "mono_repo"
    
    (root / "services" / "auth" / "src").mkdir(parents=True)
    (root / "services" / "db" / "migrations").mkdir(parents=True)
    (root / "infra" / "terraform").mkdir(parents=True)
    
    # Create multiple files with predictable content
    for i in range(10):
        (root / "services" / "auth" / "src" / f"user_model_{i}.py").write_text(
            f"# User Model {i}\n"
            f"class User{i}:\n"
            f"    id: int\n"
            f"    name: str = 'user_{i}'\n"
        )
    
    (root / "infra" / "terraform" / "main.tf").write_text(
        'provider "aws" {\n'
        '  region = "us-west-2"\n'
        '}\n\n'
        'resource "aws_instance" "app" {\n'
        '  ami           = "ami-12345"\n'
        '  instance_type = "t2.micro"\n'
        '}\n'
    )
    with patch('pathlib.Path.cwd', return_value=root):
        yield root

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_stress_json_multi_level_refactor(mock_confirm, complex_project):
    """
    Simulates a complex JSON-based refactor across a deep directory structure.
    1. Create 3 new SQL migration files.
    2. Edit all 10 user model files to add an email field.
    3. Edit the Terraform file twice: once by line number, once by content.
    Total: 3 creations, 12 edits = 15 operations
    """
    
    ops = []

    # 1. Create 3 new SQL migration files
    for i in range(3):
        ops.append({
            "file_path": f"services/db/migrations/00{i}_add_table.sql",
            "operation": "create_file",
            "content": f"CREATE TABLE table_{i} (id INT PRIMARY KEY);"
        })

    # 2. Edit all 10 user model files
    for i in range(10):
        ops.append({
            "file_path": f"services/auth/src/user_model_{i}.py",
            "operation": "insert_after",
            "locator": {
                "type": "block_content",
                "value": f"    name: str = 'user_{i}'\n"
            },
            "content": f"    email: str = 'user_{i}@example.com'"
        })
    
    # 3. Edit Terraform file
    tf_path = "infra/terraform/main.tf"
    ops.append({
        "file_path": tf_path,
        "operation": "replace_block",
        "locator": {"type": "line_number", "value": "7"},
        "content": '  instance_type = "t3.large"'
    })
    ops.append({
        "file_path": tf_path,
        "operation": "insert_after",
        "locator": {
            "type": "block_content",
            "value": '  instance_type = "t3.large"\n'
        },
        "content": '  tags = {\n    Name = "app-instance"\n  }'
    })
    
    assert len(ops) == 15

    json_replacer.preview_and_apply_json(ops, False, True)

    # Verify changes
    for i in range(3):
        assert (complex_project / f"services/db/migrations/00{i}_add_table.sql").exists()

    for i in range(10):
        model_content = (complex_project / f"services/auth/src/user_model_{i}.py").read_text()
        assert f"email: str = 'user_{i}@example.com'" in model_content
    
    tf_content = (complex_project / tf_path).read_text()
    assert 'instance_type = "t2.micro"' not in tf_content
    assert 'instance_type = "t3.large"' in tf_content
    assert 'Name = "app-instance"' in tf_content
