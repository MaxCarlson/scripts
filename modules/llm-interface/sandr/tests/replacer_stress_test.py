# File: sandr/tests/replacer_stress_test.py

import pytest
from pathlib import Path
from unittest.mock import patch

from sandr import replacer

@pytest.fixture
def complex_project(tmp_path: Path):
    """Creates a large, multi-level project for stress testing."""
    root = tmp_path / "mono_repo"
    
    # Create a deep structure
    (root / "services" / "api" / "src").mkdir(parents=True)
    (root / "services" / "worker" / "src").mkdir(parents=True)
    (root / "libs" / "shared_utils" / "src").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    
    # Create dozens of files
    for i in range(5):
        (root / "services" / "api" / "src" / f"handler_{i}.py").write_text(f"# Handler {i}\n\ndef handle_request_{i}():\n    # Original logic for {i}\n    pass\n")
        (root / "libs" / "shared_utils" / "src" / f"util_{i}.py").write_text(f"# Util {i}\n\nclass UtilClass{i}:\n    pass\n")
    
    (root / "entrypoint.sh").write_text("#!/bin/bash\n\necho 'Starting services...'\n")
    (root / "README.md").write_text("# Mono Repo\n\nOverview.\n\n## Services\n- API\n- Worker\n")

    with patch('pathlib.Path.cwd', return_value=root):
        yield root

@patch('rich.prompt.Confirm.ask', return_value=True)
def test_stress_massive_refactor(mock_confirm, complex_project):
    """
    Simulates a huge refactoring operation:
    1. Create 5 new documentation files.
    2. Edit all 5 handler files in the API service.
    3. Edit all 5 util files in the shared library by deleting their content.
    4. Append a new section to the main README.md.
    Total: 5 creations, 11 edits => 16 operations.
    """
    
    clipboard_parts = []
    
    # 1. Create 5 new doc files
    for i in range(5):
        doc_path = f"docs/service_{i}_guide.md"
        clipboard_parts.append(
            f"[START_FILE_CREATE: {doc_path}]\n"
            f"# Guide for Service {i}\n\n"
            f"Details about service {i}.\n"
            "[END_FILE]"
        )

    # 2. Edit all 5 handler files
    for i in range(5):
        handler_path = f"services/api/src/handler_{i}.py"
        clipboard_parts.append(
            f"[START_FILE_EDIT: {handler_path}]\n"
            f"<<<<<<< SEARCH\n"
            f"def handle_request_{i}():\n"
            f"    # Original logic for {i}\n"
            f"    pass\n"
            f"=======\n"
            f"from libs.shared_utils.src.util_{i} import UtilClass{i}\n\n"
            f"def handle_request_{i}():\n"
            f"    # New, improved logic for {i}\n"
            f"    u = UtilClass{i}()\n"
            f"    return True\n"
            f">>>>>>> REPLACE\n"
            "[END_FILE]"
        )

    # 3. Edit all 5 util files (delete their content)
    for i in range(5):
        util_path = f"libs/shared_utils/src/util_{i}.py"
        content_to_delete = (complex_project / util_path).read_text()
        clipboard_parts.append(
            f"[START_FILE_EDIT: {util_path}]\n"
            f"<<<<<<< SEARCH\n"
            f"{content_to_delete}"
            f"=======\n"
            f">>>>>>> REPLACE\n"
            "[END_FILE]"
        )
    
    # 4. Edit README
    readme_path = "README.md"
    clipboard_parts.append(
        f"[START_FILE_EDIT: {readme_path}]\n"
        f"<<<<<<< INSERT\n\n"
        f"## Deployment\n"
        f"Instructions for deployment.\n"
        f"=======\n"
        f"AFTER\n"
        f"<<<<<<< ANCHOR\n"
        f"- Worker\n"
        f">>>>>>> ANCHOR\n"
        "[END_FILE]"
    )

    clipboard = "\n".join(clipboard_parts)
    ops = replacer.parse_clipboard_content(clipboard)
    assert len(ops) == (5 + 5 + 5 + 1) # 16 operations

    # Apply the changes
    replacer.preview_and_apply_changes(ops, dry_run=False, auto_confirm=True)

    # Verify changes
    for i in range(5):
        assert (complex_project / f"docs/service_{i}_guide.md").exists()
        handler_content = (complex_project / f"services/api/src/handler_{i}.py").read_text()
        assert "# Original logic" not in handler_content
        assert "# New, improved logic" in handler_content
        assert (complex_project / f"libs/shared_utils/src/util_{i}.py").read_text() == ""

    readme_content = (complex_project / "README.md").read_text()
    assert "## Deployment" in readme_content
