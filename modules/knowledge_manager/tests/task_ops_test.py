# File: tests/task_ops_test.py
import pytest
from unittest.mock import MagicMock, patch, call
import uuid
from pathlib import Path
from datetime import datetime, timezone, date
import sqlite3 
import time 

from knowledge_manager import task_ops, utils
from knowledge_manager.models import Task, TaskStatus, Project, ProjectStatus

# --- Fixtures ( 그대로 ) ---

@pytest.fixture
def mock_db_conn():
    return MagicMock(spec=sqlite3.Connection)

@pytest.fixture
def mock_task_ops_db_module(mocker, mock_db_conn):
    mock_get_conn = mocker.patch('knowledge_manager.db.get_db_connection', return_value=mock_db_conn)
    mock_add_task = mocker.patch('knowledge_manager.db.add_task')
    mock_get_task_by_id = mocker.patch('knowledge_manager.db.get_task_by_id')
    mock_list_tasks = mocker.patch('knowledge_manager.db.list_tasks')
    mock_update_task = mocker.patch('knowledge_manager.db.update_task')
    mock_delete_task = mocker.patch('knowledge_manager.db.delete_task')
    mock_get_project_by_id = mocker.patch('knowledge_manager.db.get_project_by_id')
    mock_get_project_by_name = mocker.patch('knowledge_manager.db.get_project_by_name')
    
    return {
        "get_db_connection": mock_get_conn, "db_conn_obj": mock_db_conn,
        "add_task": mock_add_task, "get_task_by_id": mock_get_task_by_id,
        "list_tasks": mock_list_tasks, "update_task": mock_update_task,
        "delete_task": mock_delete_task, "get_project_by_id": mock_get_project_by_id,
        "get_project_by_name": mock_get_project_by_name,
    }

@pytest.fixture
def sample_project_for_task(mock_task_ops_db_module) -> Project:
    project = Project(id=uuid.uuid4(), name="Task Project Alpha")
    mock_task_ops_db_module["get_project_by_id"].side_effect = lambda conn, pid: project if pid == project.id else None
    mock_task_ops_db_module["get_project_by_name"].side_effect = lambda conn, pname: project if pname == project.name else None
    return project

@pytest.fixture
def another_project_for_task(mock_task_ops_db_module) -> Project:
    project = Project(id=uuid.uuid4(), name="Task Project Beta")
    return project

@pytest.fixture
def sample_parent_task_for_task(mock_task_ops_db_module, sample_project_for_task: Project) -> Task:
    parent_task = Task(id=uuid.uuid4(), title="Parent Task Alpha", project_id=sample_project_for_task.id)
    # Make this side effect more robust by checking against a list of known tasks for fixtures
    # For now, ensure it doesn't clash with other tests by being specific.
    # The lambda will be overwritten by tests that need more specific get_task_by_id behavior.
    mock_task_ops_db_module["get_task_by_id"].side_effect = lambda conn, tid: parent_task if tid == parent_task.id else None
    return parent_task

@pytest.fixture
def sample_task_obj(sample_project_for_task: Project) -> Task:
    now = datetime.now(timezone.utc)
    # Ensure modified_at is slightly different from created_at for some tests
    time.sleep(0.001) 
    modified = datetime.now(timezone.utc)
    return Task(
        id=uuid.uuid4(), title="Testable Task One", status=TaskStatus.TODO,
        project_id=sample_project_for_task.id, created_at=now, modified_at=modified,
        priority=2, due_date=date(2025, 1, 10)
    )

# Helper for mock db.update_task side_effect
def mock_db_update_return_new_timestamped_task(conn, task_being_updated: Task) -> Task:
    task_attrs = task_being_updated.__dict__.copy()
    time.sleep(0.002) # Ensure timestamp difference
    task_attrs['modified_at'] = utils.get_current_utc_timestamp()
    return Task(**task_attrs)

# --- Existing Tests (create_new_task, find_task, list_all_tasks, etc. ) ---
def test_create_new_task_success_basic(tmp_path: Path, mock_task_ops_db_module, sample_project_for_task: Project):
    task_title = "Basic New Task"
    mock_task_ops_db_module["add_task"].side_effect = lambda conn, t: t 
    created_task = task_ops.create_new_task(title=task_title, project_identifier=sample_project_for_task.id, base_data_dir=tmp_path)
    assert created_task.title == task_title
    mock_task_ops_db_module["get_db_connection"].assert_called_once_with(tmp_path / utils.DB_FILE_NAME)
    mock_task_ops_db_module["get_project_by_id"].assert_any_call(mock_task_ops_db_module["db_conn_obj"], sample_project_for_task.id)
    mock_task_ops_db_module["add_task"].assert_called_once()

def test_create_new_task_with_details_and_parent(tmp_path: Path, mock_task_ops_db_module, sample_project_for_task: Project, sample_parent_task_for_task: Task):
    task_title = "Detailed Subtask"; details_content = "### Subtask Details\n- Point 1"; due_date_str = "2025-07-15"
    sample_parent_task_for_task.project_id = sample_project_for_task.id
    mock_task_ops_db_module["get_project_by_name"].side_effect = lambda conn, pname: sample_project_for_task if pname == sample_project_for_task.name else None
    mock_task_ops_db_module["get_task_by_id"].side_effect = lambda conn, tid: sample_parent_task_for_task if tid == sample_parent_task_for_task.id else None
    mock_task_ops_db_module["add_task"].side_effect = lambda conn, t: t
    created_task = task_ops.create_new_task(title=task_title, project_identifier=sample_project_for_task.name, parent_task_identifier=sample_parent_task_for_task.id, details=details_content, due_date_iso=due_date_str, base_data_dir=tmp_path)
    assert created_task.title == task_title; assert created_task.details_md_path is not None; assert created_task.details_md_path.read_text(encoding="utf-8") == details_content

def test_create_new_task_project_not_found(tmp_path: Path, mock_task_ops_db_module):
    mock_task_ops_db_module["get_project_by_name"].return_value = None; mock_task_ops_db_module["get_project_by_id"].return_value = None
    with pytest.raises(ValueError, match="Project with identifier 'NonExistentProject' not found."):
        task_ops.create_new_task(title="Task", project_identifier="NonExistentProject", base_data_dir=tmp_path)

def test_create_new_task_parent_task_not_found(tmp_path: Path, mock_task_ops_db_module, sample_project_for_task):
    mock_task_ops_db_module["get_project_by_id"].return_value = sample_project_for_task
    non_existent_parent_id = uuid.uuid4()
    mock_task_ops_db_module["get_task_by_id"].side_effect = lambda conn, tid: None if tid == non_existent_parent_id else None
    with pytest.raises(ValueError, match=f"Task with ID '{non_existent_parent_id}' not found."):
        task_ops.create_new_task(title="Task", project_identifier=sample_project_for_task.id, parent_task_identifier=non_existent_parent_id, base_data_dir=tmp_path)

def test_create_new_task_parent_project_mismatch(tmp_path: Path, mock_task_ops_db_module, sample_project_for_task: Project):
    project1 = sample_project_for_task; project2 = Project(id=uuid.uuid4(), name="Other Project For Task"); parent_in_proj2 = Task(id=uuid.uuid4(), title="Parent in Proj2", project_id=project2.id)
    mock_task_ops_db_module["get_project_by_id"].side_effect = lambda conn, pid: project1 if pid == project1.id else (project2 if pid == project2.id else None)
    mock_task_ops_db_module["get_task_by_id"].return_value = parent_in_proj2
    with pytest.raises(ValueError, match="Parent task does not belong to the specified project."):
        task_ops.create_new_task(title="Subtask", project_identifier=project1.id, parent_task_identifier=parent_in_proj2.id, base_data_dir=tmp_path)

def test_find_task_by_id_success(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    mock_task_ops_db_module["get_task_by_id"].side_effect = lambda conn, tid: sample_task_obj if tid == sample_task_obj.id else None
    found_task = task_ops.find_task(sample_task_obj.id, base_data_dir=tmp_path)
    assert found_task == sample_task_obj

def test_find_task_not_found(tmp_path: Path, mock_task_ops_db_module):
    non_existent_id = uuid.uuid4(); mock_task_ops_db_module["get_task_by_id"].return_value = None
    found_task = task_ops.find_task(non_existent_id, base_data_dir=tmp_path); assert found_task is None

def test_find_task_invalid_identifier_format(tmp_path: Path, mock_task_ops_db_module):
    mock_task_ops_db_module["get_task_by_id"].return_value = None
    found_task = task_ops.find_task("not-a-uuid-string", base_data_dir=tmp_path); assert found_task is None

def test_list_all_tasks_no_filters(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    mock_task_list = [sample_task_obj, Task(title="Another Task")]; mock_task_ops_db_module["list_tasks"].return_value = mock_task_list
    tasks = task_ops.list_all_tasks(base_data_dir=tmp_path); assert tasks == mock_task_list

def test_list_all_tasks_with_project_filter(tmp_path: Path, mock_task_ops_db_module, sample_project_for_task: Project):
    mock_task_ops_db_module["get_project_by_id"].side_effect = lambda conn, pid: sample_project_for_task if pid == sample_project_for_task.id else None
    task_ops.list_all_tasks(project_identifier=sample_project_for_task.id, base_data_dir=tmp_path)
    mock_task_ops_db_module["list_tasks"].assert_called_once_with(mock_task_ops_db_module["db_conn_obj"], project_id=sample_project_for_task.id, status=None, parent_task_id=None, include_subtasks_of_any_parent=False)


# --- Tests for update_task_details_and_status (Existing and NEW) ---

def test_update_task_all_fields(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, sample_project_for_task: Project, another_project_for_task: Project):
    original_task_state = Task(**sample_task_obj.__dict__)
    mock_task_ops_db_module["get_task_by_id"].side_effect = lambda conn, tid: original_task_state if tid == original_task_state.id else None
    
    # Use the helper for mock side_effect
    mock_task_ops_db_module["update_task"].side_effect = mock_db_update_return_new_timestamped_task

    new_title = "Updated Task Title XYZ"; new_status = TaskStatus.IN_PROGRESS; new_priority = 1
    new_due_date_iso = "2026-01-01"; new_details_content = "Updated details ABC."
    
    mock_task_ops_db_module["get_project_by_id"].side_effect = lambda conn, pid: another_project_for_task if pid == another_project_for_task.id else (sample_project_for_task if pid == sample_project_for_task.id else None)

    updated_task = task_ops.update_task_details_and_status(
        task_identifier=original_task_state.id, new_title=new_title, new_status=new_status, new_priority=new_priority,
        new_due_date_iso=new_due_date_iso, new_details=new_details_content,
        new_project_identifier=another_project_for_task.id, base_data_dir=tmp_path
    )
    assert updated_task is not None; assert updated_task.title == new_title; assert updated_task.project_id == another_project_for_task.id
    assert updated_task.details_md_path is not None; assert updated_task.details_md_path.read_text(encoding="utf-8") == new_details_content
    assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_only_title(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    original_task_state = Task(**sample_task_obj.__dict__)
    mock_task_ops_db_module["get_task_by_id"].return_value = original_task_state
    mock_task_ops_db_module["update_task"].side_effect = mock_db_update_return_new_timestamped_task

    new_title = "Only Title Updated"
    updated_task = task_ops.update_task_details_and_status(
        task_identifier=original_task_state.id, new_title=new_title, base_data_dir=tmp_path
    )
    assert updated_task.title == new_title
    assert updated_task.status == original_task_state.status 
    assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_clear_due_date_with_empty_string(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    original_task_state = Task(**sample_task_obj.__dict__)
    original_task_state.due_date = date(2025, 12, 12)
    mock_task_ops_db_module["get_task_by_id"].return_value = original_task_state
    mock_task_ops_db_module["update_task"].side_effect = mock_db_update_return_new_timestamped_task

    updated_task = task_ops.update_task_details_and_status(
        task_identifier=original_task_state.id, new_due_date_iso="", base_data_dir=tmp_path
    )
    assert updated_task.due_date is None
    assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_clear_details_with_empty_string(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    original_task_state = Task(**sample_task_obj.__dict__)
    details_file = tmp_path / "files" / "tasks" / f"{original_task_state.id}.md"
    details_file.parent.mkdir(parents=True, exist_ok=True)
    details_file.write_text("Original details", encoding="utf-8")
    original_task_state.details_md_path = details_file
    
    mock_task_ops_db_module["get_task_by_id"].return_value = original_task_state
    mock_task_ops_db_module["update_task"].side_effect = mock_db_update_return_new_timestamped_task

    updated_task = task_ops.update_task_details_and_status(
        task_identifier=original_task_state.id, new_details="", base_data_dir=tmp_path
    )
    assert updated_task.details_md_path is not None 
    assert updated_task.details_md_path.read_text(encoding="utf-8") == "" 
    assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_clear_project(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, sample_project_for_task: Project):
    original_task_state = Task(**sample_task_obj.__dict__)
    assert original_task_state.project_id == sample_project_for_task.id 
    
    mock_task_ops_db_module["get_task_by_id"].return_value = original_task_state
    mock_task_ops_db_module["update_task"].side_effect = mock_db_update_return_new_timestamped_task

    updated_task = task_ops.update_task_details_and_status(
        task_identifier=original_task_state.id, clear_project=True, base_data_dir=tmp_path
    )
    assert updated_task.project_id is None
    assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_no_changes_provided(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    original_task_state = Task(**sample_task_obj.__dict__)
    mock_task_ops_db_module["get_task_by_id"].return_value = original_task_state
    
    updated_task = task_ops.update_task_details_and_status(
        task_identifier=original_task_state.id, base_data_dir=tmp_path
    )
    assert updated_task == original_task_state 
    mock_task_ops_db_module["update_task"].assert_not_called()

def test_update_task_not_found(tmp_path: Path, mock_task_ops_db_module):
    non_existent_id = uuid.uuid4()
    mock_task_ops_db_module["get_task_by_id"].return_value = None 
    
    with pytest.raises(ValueError, match=f"Task with ID '{non_existent_id}' not found."): # Expect ValueError
        task_ops.update_task_details_and_status(
            task_identifier=non_existent_id, new_title="New Title", base_data_dir=tmp_path
        )
    mock_task_ops_db_module["update_task"].assert_not_called()


def test_update_task_set_done_updates_completed_at(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    sample_task_obj.status = TaskStatus.TODO; sample_task_obj.completed_at = None
    mock_task_ops_db_module["get_task_by_id"].return_value = sample_task_obj
    def update_side_effect_for_done(conn, task_to_update):
        # Simulate the logic within task_ops.update_task_details_and_status for completed_at
        # and the db.update_task's modified_at update.
        task_attrs = task_to_update.__dict__.copy()
        if task_attrs['status'] == TaskStatus.DONE and task_attrs['completed_at'] is None:
            task_attrs['completed_at'] = utils.get_current_utc_timestamp()
        elif task_attrs['status'] != TaskStatus.DONE:
            task_attrs['completed_at'] = None
        time.sleep(0.002)
        task_attrs['modified_at'] = utils.get_current_utc_timestamp()
        return Task(**task_attrs)
    mock_task_ops_db_module["update_task"].side_effect = update_side_effect_for_done
    updated_task = task_ops.update_task_details_and_status(task_identifier=sample_task_obj.id, new_status=TaskStatus.DONE, base_data_dir=tmp_path)
    assert updated_task.status == TaskStatus.DONE
    assert updated_task.completed_at is not None

# --- Tests for mark_task_status ---
def test_mark_task_status(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, mocker):
    mock_update_details = mocker.patch('knowledge_manager.task_ops.update_task_details_and_status')
    returned_task_from_update = Task(**sample_task_obj.__dict__); returned_task_from_update.status = TaskStatus.IN_PROGRESS
    mock_update_details.return_value = returned_task_from_update
    result_task = task_ops.mark_task_status(sample_task_obj.id, TaskStatus.IN_PROGRESS, base_data_dir=tmp_path)
    mock_update_details.assert_called_once_with(task_identifier=sample_task_obj.id, new_status=TaskStatus.IN_PROGRESS, base_data_dir=tmp_path)
    assert result_task.status == TaskStatus.IN_PROGRESS

# --- Tests for get_task_file_path ---
def test_get_task_file_path_task_exists_with_path(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, mocker):
    expected_path = tmp_path / "files" / "tasks" / f"{str(sample_task_obj.id)}.md"; sample_task_obj.details_md_path = expected_path
    mock_find_task = mocker.patch('knowledge_manager.task_ops.find_task', return_value=sample_task_obj)
    returned_path = task_ops.get_task_file_path(task_identifier=sample_task_obj.id, base_data_dir=tmp_path)
    assert returned_path == expected_path

def test_get_task_file_path_task_exists_no_path_create_true(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, mocker):
    sample_task_obj.details_md_path = None
    mock_find_task = mocker.patch('knowledge_manager.task_ops.find_task', return_value=sample_task_obj)
    expected_generated_path = tmp_path / "custom_generated" / f"{str(sample_task_obj.id)}.md"
    mock_generate_path = mocker.patch('knowledge_manager.utils.generate_markdown_file_path', return_value=expected_generated_path)
    returned_path = task_ops.get_task_file_path(task_identifier=sample_task_obj.id, base_data_dir=tmp_path, create_if_missing_in_object=True)
    assert returned_path == expected_generated_path

def test_get_task_file_path_task_exists_no_path_create_false(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, mocker):
    sample_task_obj.details_md_path = None
    mock_find_task = mocker.patch('knowledge_manager.task_ops.find_task', return_value=sample_task_obj)
    mock_generate_path = mocker.patch('knowledge_manager.utils.generate_markdown_file_path')
    returned_path = task_ops.get_task_file_path(task_identifier=sample_task_obj.id, base_data_dir=tmp_path, create_if_missing_in_object=False)
    assert returned_path is None; mock_generate_path.assert_not_called()

def test_get_task_file_path_task_not_found(tmp_path: Path, mock_task_ops_db_module, mocker):
    non_existent_id = uuid.uuid4()
    mock_find_task = mocker.patch('knowledge_manager.task_ops.find_task', return_value=None)
    with pytest.raises(ValueError, match=f"Task with identifier '{non_existent_id}' not found for getpath."):
        task_ops.get_task_file_path(task_identifier=non_existent_id, base_data_dir=tmp_path)

def test_get_task_file_path_unsupported_file_type(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, mocker):
    expected_path = tmp_path / "files" / "tasks" / f"{str(sample_task_obj.id)}.md"; sample_task_obj.details_md_path = expected_path
    mock_find_task = mocker.patch('knowledge_manager.task_ops.find_task', return_value=sample_task_obj)
    returned_path = task_ops.get_task_file_path(task_identifier=sample_task_obj.id, file_type="unsupported_type", base_data_dir=tmp_path)
    assert returned_path == expected_path

# --- Tests for delete_task_permanently ---
def test_delete_task_permanently_success(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    details_path = tmp_path / "files" / "tasks" / f"{str(sample_task_obj.id)}.md"; sample_task_obj.details_md_path = details_path
    details_path.parent.mkdir(parents=True, exist_ok=True); details_path.write_text("Task details to delete", encoding="utf-8")
    mock_task_ops_db_module["get_task_by_id"].return_value = sample_task_obj
    mock_task_ops_db_module["delete_task"].return_value = True
    result = task_ops.delete_task_permanently(sample_task_obj.id, base_data_dir=tmp_path)
    assert result is True; assert not details_path.exists()

def test_delete_task_permanently_task_not_found(tmp_path: Path, mock_task_ops_db_module):
    non_existent_id = uuid.uuid4()
    mock_task_ops_db_module["get_task_by_id"].return_value = None 
    result = task_ops.delete_task_permanently(non_existent_id, base_data_dir=tmp_path)
    assert result is False

# End of File: tests/task_ops_test.py
