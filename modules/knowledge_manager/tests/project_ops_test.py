# File: tests/project_ops_test.py
import pytest
from unittest.mock import MagicMock, patch, call
import uuid
from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import time 

from knowledge_manager import project_ops, utils, db
from knowledge_manager.models import Project, ProjectStatus

@pytest.fixture
def mock_db_conn():
    return MagicMock(spec=sqlite3.Connection)

@pytest.fixture
def mock_project_ops_db_module(mocker, mock_db_conn):
    mocker.patch('knowledge_manager.db.get_db_connection', return_value=mock_db_conn)
    mocker.patch('knowledge_manager.db.add_project')
    mocker.patch('knowledge_manager.db.get_project_by_id')
    mocker.patch('knowledge_manager.db.get_project_by_name')
    mocker.patch('knowledge_manager.db.list_projects')
    mocker.patch('knowledge_manager.db.update_project')
    mocker.patch('knowledge_manager.db.delete_project')
    
    return {
        "get_db_connection": db.get_db_connection,
        "db_conn_obj": mock_db_conn,
        "add_project": db.add_project,
        "get_project_by_id": db.get_project_by_id,
        "get_project_by_name": db.get_project_by_name,
        "list_projects": db.list_projects,
        "update_project": db.update_project,
        "delete_project": db.delete_project,
    }

@pytest.fixture
def sample_project_data():
    now = datetime.now(timezone.utc)
    return {
        "id": uuid.uuid4(), "name": "Galaxy Quest", "status": ProjectStatus.ACTIVE,
        "created_at": now, "modified_at": now,
        "description_md_path": None 
    }

@pytest.fixture
def sample_project_obj(sample_project_data):
    return Project(**sample_project_data)

# --- Tests for create_new_project ---

def test_create_new_project_success_no_description(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    project_name = "New Galactic Empire"
    mock_project_ops_db_module["get_project_by_name"].return_value = None
    
    def mock_db_add_side_effect(conn, proj_to_add: Project) -> Project:
        time.sleep(0.001)
        proj_to_add.modified_at = utils.get_current_utc_timestamp()
        return proj_to_add
    mock_project_ops_db_module["add_project"].side_effect = mock_db_add_side_effect

    created_project = project_ops.create_new_project(
        name=project_name, status=ProjectStatus.BACKLOG, base_data_dir=tmp_path
    )

    assert created_project.name == project_name
    assert created_project.status == ProjectStatus.BACKLOG
    assert created_project.description_md_path is None
    
    mock_project_ops_db_module["get_db_connection"].assert_called_once_with(tmp_path / utils.DB_FILE_NAME)
    mock_project_ops_db_module["get_project_by_name"].assert_called_once_with(mock_project_ops_db_module["db_conn_obj"], project_name)
    mock_project_ops_db_module["add_project"].assert_called_once()
    added_arg = mock_project_ops_db_module["add_project"].call_args[0][1]
    assert added_arg.name == project_name
    assert (created_project.modified_at - added_arg.created_at).total_seconds() >= 0
    
    mock_project_ops_db_module["db_conn_obj"].close.assert_called_once()


def test_create_new_project_success_with_description(tmp_path: Path, mock_project_ops_db_module):
    project_name = "Project With Desc"
    description_content = "# My Project\nDetails here."
    mock_project_ops_db_module["get_project_by_name"].return_value = None
    mock_project_ops_db_module["add_project"].side_effect = lambda conn, p: p

    created_project = project_ops.create_new_project(
        name=project_name, description=description_content, base_data_dir=tmp_path
    )

    assert created_project.description_md_path is not None
    assert created_project.description_md_path.name == f"{str(created_project.id)}.md"
    assert created_project.description_md_path.parent == tmp_path / "files" / "projects"
    assert created_project.description_md_path.exists()
    assert created_project.description_md_path.read_text(encoding="utf-8") == description_content

def test_create_new_project_name_conflict(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    mock_project_ops_db_module["get_project_by_name"].return_value = sample_project_obj
    with pytest.raises(ValueError, match=f"A project with the name '{sample_project_obj.name}' already exists."):
        project_ops.create_new_project(name=sample_project_obj.name, base_data_dir=tmp_path)
    mock_project_ops_db_module["add_project"].assert_not_called()

# --- Tests for find_project ---

def test_find_project_by_id_success(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    project_id_str = str(sample_project_obj.id)
    mock_project_ops_db_module["get_project_by_id"].return_value = sample_project_obj

    found_project = project_ops.find_project(project_id_str, base_data_dir=tmp_path)
    assert found_project == sample_project_obj
    mock_project_ops_db_module["get_project_by_id"].assert_called_with(mock_project_ops_db_module["db_conn_obj"], sample_project_obj.id)

def test_find_project_by_uuid_object_success(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    """Tests that find_project works when passed a UUID object directly."""
    mock_project_ops_db_module["get_project_by_id"].return_value = sample_project_obj
    
    found_project = project_ops.find_project(sample_project_obj.id, base_data_dir=tmp_path)
    
    assert found_project == sample_project_obj
    mock_project_ops_db_module["get_project_by_id"].assert_called_once_with(mock_project_ops_db_module["db_conn_obj"], sample_project_obj.id)
    mock_project_ops_db_module["get_project_by_name"].assert_not_called()

def test_find_project_by_name_success(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    project_name = sample_project_obj.name
    mock_project_ops_db_module["get_project_by_id"].return_value = None 
    mock_project_ops_db_module["get_project_by_name"].return_value = sample_project_obj

    found_project = project_ops.find_project(project_name, base_data_dir=tmp_path)
    assert found_project == sample_project_obj
    mock_project_ops_db_module["get_project_by_name"].assert_called_with(mock_project_ops_db_module["db_conn_obj"], project_name)

def test_find_project_not_found(tmp_path: Path, mock_project_ops_db_module):
    identifier = "NonExistent"
    mock_project_ops_db_module["get_project_by_id"].return_value = None
    mock_project_ops_db_module["get_project_by_name"].return_value = None
    
    found_project = project_ops.find_project(identifier, base_data_dir=tmp_path)
    assert found_project is None

# --- Tests for list_all_projects ---

def test_list_all_projects_success(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    mock_projects_list = [sample_project_obj, Project(name="Another Project")]
    mock_project_ops_db_module["list_projects"].return_value = mock_projects_list

    projects = project_ops.list_all_projects(base_data_dir=tmp_path)
    assert projects == mock_projects_list
    mock_project_ops_db_module["list_projects"].assert_called_once_with(mock_project_ops_db_module["db_conn_obj"], status=None)

# --- Tests for update_project_details ---

def test_update_project_details_all_fields(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    original_project_as_found = Project(**sample_project_obj.__dict__)
    
    with patch('knowledge_manager.project_ops.find_project', return_value=original_project_as_found) as mock_find:
        mock_project_ops_db_module["get_project_by_name"].return_value = None

        def mock_db_update_side_effect(conn, project_passed_to_db: Project) -> Project:
            project_returned_by_db = Project(**project_passed_to_db.__dict__)
            time.sleep(0.005)
            project_returned_by_db.modified_at = utils.get_current_utc_timestamp()
            return project_returned_by_db

        mock_project_ops_db_module["update_project"].side_effect = mock_db_update_side_effect

        new_name = "Updated Galaxy Quest Name XYZ"
        new_status = ProjectStatus.COMPLETED
        new_desc = "## Updated Description Content ABC\nAll done now for sure."
    
        updated_project_from_ops = project_ops.update_project_details(
            project_identifier=str(original_project_as_found.id),
            new_name=new_name, new_status=new_status, new_description=new_desc,
            base_data_dir=tmp_path
        )

        assert updated_project_from_ops is not None
        assert updated_project_from_ops.name == new_name
        assert updated_project_from_ops.status == new_status
        desc_file_path = tmp_path / "files" / "projects" / f"{str(original_project_as_found.id)}.md"
        assert updated_project_from_ops.description_md_path == desc_file_path
        assert desc_file_path.exists()
        assert desc_file_path.read_text(encoding="utf-8") == new_desc
    
        mock_project_ops_db_module["update_project"].assert_called_once()
        updated_arg_passed_to_db = mock_project_ops_db_module["update_project"].call_args[0][1]
        assert updated_arg_passed_to_db.name == new_name
        assert updated_project_from_ops.modified_at > original_project_as_found.modified_at

def test_update_project_details_by_uuid_object(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    with patch('knowledge_manager.project_ops.find_project', return_value=sample_project_obj) as mock_find:
        mock_project_ops_db_module["get_project_by_name"].return_value = None
        mock_project_ops_db_module["update_project"].side_effect = lambda conn, p: p
        
        new_name = "Updated Via UUID Object"

        updated_project = project_ops.update_project_details(
            project_identifier=sample_project_obj.id,
            new_name=new_name,
            base_data_dir=tmp_path
        )

        assert updated_project is not None
        assert updated_project.name == new_name
        mock_find.assert_called_once_with(sample_project_obj.id, base_data_dir=tmp_path)
        mock_project_ops_db_module["update_project"].assert_called_once()

def test_update_project_details_project_not_found(tmp_path: Path, mock_project_ops_db_module):
    with patch('knowledge_manager.project_ops.find_project', return_value=None):
        result = project_ops.update_project_details("nonexistent", base_data_dir=tmp_path)
        assert result is None
        mock_project_ops_db_module["update_project"].assert_not_called()

# --- Tests for get_project_with_details ---
def test_get_project_with_details_success(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    desc_content = "# Project Alpha\nDetails..."
    desc_file_path = tmp_path / "files" / "projects" / f"{str(sample_project_obj.id)}.md"
    sample_project_obj.description_md_path = desc_file_path
    
    with patch('knowledge_manager.project_ops.find_project', return_value=sample_project_obj):
        desc_file_path.parent.mkdir(parents=True, exist_ok=True)
        desc_file_path.write_text(desc_content, encoding="utf-8")

        result_project, result_desc = project_ops.get_project_with_details(
            str(sample_project_obj.id), base_data_dir=tmp_path
        )
        assert result_project == sample_project_obj
        assert result_desc == desc_content

# --- Tests for delete_project_permanently ---
def test_delete_project_permanently_success(tmp_path: Path, mock_project_ops_db_module, sample_project_obj):
    desc_path = tmp_path / "files" / "projects" / f"{str(sample_project_obj.id)}.md"
    sample_project_obj.description_md_path = desc_path
    desc_path.parent.mkdir(parents=True, exist_ok=True)
    desc_path.write_text("to be deleted", encoding="utf-8")
    assert desc_path.exists()

    with patch('knowledge_manager.project_ops.find_project', return_value=sample_project_obj):
        mock_project_ops_db_module["delete_project"].return_value = True

        result = project_ops.delete_project_permanently(str(sample_project_obj.id), base_data_dir=tmp_path)

        assert result is True
        assert not desc_path.exists()
        mock_project_ops_db_module["delete_project"].assert_called_with(mock_project_ops_db_module["db_conn_obj"], sample_project_obj.id)
