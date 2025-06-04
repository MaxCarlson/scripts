# File: tests/utils_test.py
import pytest
from pathlib import Path
import uuid
from datetime import datetime, timezone

# Import from the package directly
from knowledge_manager import utils

# --- Test Path Management ---

def test_get_base_data_dir_default(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    expected_dir = tmp_path / ".local" / "share" / utils.DEFAULT_BASE_DATA_DIR_NAME
    base_dir = utils.get_base_data_dir()
    assert base_dir == expected_dir
    assert base_dir.exists()

def test_get_base_data_dir_user_specified(tmp_path: Path):
    user_dir = tmp_path / "my_custom_km_data"
    base_dir = utils.get_base_data_dir(user_dir)
    assert base_dir == user_dir
    assert base_dir.exists()

def test_get_db_path(tmp_path: Path):
    base_data_dir = tmp_path / "km_data_for_db_test"
    db_path = utils.get_db_path(base_data_dir)
    expected_db_path = base_data_dir / utils.DB_FILE_NAME
    assert db_path == expected_db_path
    assert db_path.parent.exists()

def test_get_content_files_base_dir(tmp_path: Path):
    base_data_dir = tmp_path / "km_data_content_base"
    content_base = utils.get_content_files_base_dir(base_data_dir)
    expected_path = base_data_dir / "files"
    assert content_base == expected_path
    assert content_base.exists()

def test_get_project_content_dir(tmp_path: Path):
    base_data_dir = tmp_path / "km_data_proj_content"
    proj_content_dir = utils.get_project_content_dir(base_data_dir)
    expected_path = base_data_dir / "files" / utils.PROJECT_FILES_DIR_NAME
    assert proj_content_dir == expected_path
    assert proj_content_dir.exists()

def test_get_task_content_dir(tmp_path: Path):
    base_data_dir = tmp_path / "km_data_task_content"
    task_content_dir = utils.get_task_content_dir(base_data_dir)
    expected_path = base_data_dir / "files" / utils.TASK_FILES_DIR_NAME
    assert task_content_dir == expected_path
    assert task_content_dir.exists()

def test_generate_markdown_file_path_project(tmp_path: Path):
    entity_id = uuid.uuid4()
    base_data_dir = tmp_path / "km_data_md_path_proj"
    md_path = utils.generate_markdown_file_path(entity_id, "project", base_data_dir)
    expected_parent = base_data_dir / "files" / utils.PROJECT_FILES_DIR_NAME
    expected_path = expected_parent / f"{str(entity_id)}.md"
    assert md_path == expected_path
    assert md_path.parent.exists()

def test_generate_markdown_file_path_task(tmp_path: Path):
    entity_id = uuid.uuid4()
    base_data_dir = tmp_path / "km_data_md_path_task"
    md_path = utils.generate_markdown_file_path(entity_id, "task", base_data_dir)
    expected_parent = base_data_dir / "files" / utils.TASK_FILES_DIR_NAME
    expected_path = expected_parent / f"{str(entity_id)}.md"
    assert md_path == expected_path
    assert md_path.parent.exists()

def test_generate_markdown_file_path_invalid_type(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown entity_type"):
        utils.generate_markdown_file_path(uuid.uuid4(), "invalid_type", tmp_path / "km_data")

# --- Test File Operations ---

def test_write_markdown_file(tmp_path: Path):
    file_path = tmp_path / "test_dir" / "test_doc.md"
    content = "# Hello World\nThis is a test."
    assert not file_path.exists()
    utils.write_markdown_file(file_path, content)
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == content

def test_read_markdown_file_exists(tmp_path: Path):
    file_path = tmp_path / "readable.md"
    content = "Some readable content."
    file_path.write_text(content, encoding="utf-8")
    read_content = utils.read_markdown_file(file_path)
    assert read_content == content

def test_read_markdown_file_not_exists(tmp_path: Path):
    file_path = tmp_path / "non_existent.md"
    read_content = utils.read_markdown_file(file_path)
    assert read_content is None

def test_read_markdown_file_io_error(tmp_path: Path):
    dir_path = tmp_path / "a_directory"
    dir_path.mkdir()
    read_content = utils.read_markdown_file(dir_path)
    assert read_content is None

# --- Test Timestamp Utilities ---

def test_get_current_utc_timestamp():
    ts = utils.get_current_utc_timestamp()
    assert isinstance(ts, datetime)
    assert ts.tzinfo == timezone.utc
    assert (datetime.now(timezone.utc) - ts).total_seconds() < 0.1

# End of File: tests/utils_test.py
