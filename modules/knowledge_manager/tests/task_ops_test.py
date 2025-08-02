# File: tests/task_ops_test.py
import pytest
from unittest.mock import MagicMock, patch, call
import uuid
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
import sqlite3 
import time 

from knowledge_manager import task_ops, utils, db # db needed for direct calls in some mock setups
from knowledge_manager.models import Task, TaskStatus, Project, ProjectStatus

# --- Fixtures ---

@pytest.fixture
def mock_db_conn():
    return MagicMock(spec=sqlite3.Connection)

@pytest.fixture
def mock_task_ops_db_module(mocker, mock_db_conn):
    # Mock all db functions that task_ops might call
    mock_get_conn = mocker.patch('knowledge_manager.db.get_db_connection', return_value=mock_db_conn)
    
    # Task related
    mocker.patch('knowledge_manager.db.add_task')
    mocker.patch('knowledge_manager.db.get_task_by_id')
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix') # New
    mocker.patch('knowledge_manager.db.list_tasks')
    mocker.patch('knowledge_manager.db.update_task')
    mocker.patch('knowledge_manager.db.delete_task')

    # Project related (for resolving project identifiers)
    mocker.patch('knowledge_manager.db.get_project_by_id')
    mocker.patch('knowledge_manager.db.get_project_by_name')
    
    # Return a dictionary of the *actual module functions* from db, not the mocks,
    # so tests can configure individual mocks as needed using 'mocker.patch' on 'knowledge_manager.db.func_name'
    # or by accessing them via this fixture if we returned the mocks.
    # For simplicity of test setup, let tests patch 'knowledge_manager.db.*' directly.
    # This fixture primarily ensures get_db_connection is mocked.
    return {
        "get_db_connection": mock_get_conn,
        "db_conn_obj": mock_db_conn,
        # Individual mocks can be accessed via mocker.patch('knowledge_manager.db.specific_func') in tests
    }


@pytest.fixture
def sample_project_for_task(mocker) -> Project: # Removed mock_task_ops_db_module dependency
    project = Project(id=uuid.uuid4(), name="Task Project Alpha")
    # Tests needing project resolution will mock db.get_project_by_id/name
    return project

@pytest.fixture
def another_project_for_task(mocker) -> Project:
    project = Project(id=uuid.uuid4(), name="Task Project Beta")
    return project

@pytest.fixture
def sample_task_obj(sample_project_for_task: Project) -> Task:
    now = datetime.now(timezone.utc)
    time.sleep(0.001) 
    modified = datetime.now(timezone.utc)
    return Task(
        id=uuid.uuid4(), title="Unique Task Title One", status=TaskStatus.TODO,
        project_id=sample_project_for_task.id, created_at=now, modified_at=modified,
        priority=2, due_date=date(2025, 1, 10)
    )

# Helper for mock db.update_task side_effect
def mock_db_update_return_new_timestamped_task(conn, task_being_updated: Task) -> Task:
    task_attrs = task_being_updated.__dict__.copy()
    time.sleep(0.002) 
    task_attrs['modified_at'] = utils.get_current_utc_timestamp()
    return Task(**task_attrs)

# --- Tests for _resolve_task_id (Tested via public functions like find_task) ---

# --- Existing Tests for create_new_task, find_task (by ID), list_all_tasks etc. ---
# These tests primarily use UUIDs for task identification.
# We will add new tests specifically for title prefix resolution.

def test_create_new_task_success_basic(tmp_path: Path, mocker, sample_project_for_task: Project):
    task_title = "Basic New Task"
    mocker.patch('knowledge_manager.db.get_project_by_id', return_value=sample_project_for_task)
    mock_add_task = mocker.patch('knowledge_manager.db.add_task', side_effect=lambda conn, t: t)
    
    created_task = task_ops.create_new_task(title=task_title, project_identifier=sample_project_for_task.id, base_data_dir=tmp_path)
    assert created_task.title == task_title
    mock_add_task.assert_called_once()


def test_find_task_by_id_success(tmp_path: Path, mocker, sample_task_obj: Task):
    mock_get_task_by_id = mocker.patch('knowledge_manager.db.get_task_by_id', return_value=sample_task_obj)
    
    found_task = task_ops.find_task(sample_task_obj.id, base_data_dir=tmp_path)
    assert found_task == sample_task_obj
    # _resolve_task_id calls db.get_task_by_id, then find_task calls it again.
    assert mock_get_task_by_id.call_count >= 1 
    mock_get_task_by_id.assert_any_call(mocker.ANY, sample_task_obj.id)


def test_find_task_by_id_not_found(tmp_path: Path, mocker):
    non_existent_id = uuid.uuid4()
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=None)
    
    found_task = task_ops.find_task(non_existent_id, base_data_dir=tmp_path)
    assert found_task is None

# --- NEW Tests for Title Prefix Resolution ---

def test_find_task_by_unique_title_prefix(tmp_path: Path, mocker, sample_task_obj: Task):
    title_prefix = sample_task_obj.title[:5] # e.g., "Uniqu"
    
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=None) # Ensure UUID lookup fails first
    mock_get_by_prefix = mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[sample_task_obj])
    # Mock get_task_by_id again for the final fetch after resolution
    mocker.patch('knowledge_manager.db.get_task_by_id', side_effect=lambda conn, tid: sample_task_obj if tid == sample_task_obj.id else None)


    found_task = task_ops.find_task(title_prefix, base_data_dir=tmp_path)
    
    assert found_task is not None
    assert found_task.id == sample_task_obj.id
    mock_get_by_prefix.assert_called_once_with(mocker.ANY, title_prefix, project_id=None)

def test_find_task_by_unique_title_prefix_scoped_to_project(tmp_path: Path, mocker, sample_task_obj: Task, sample_project_for_task: Project):
    title_prefix = sample_task_obj.title[:5]
    
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=None)
    mock_get_by_prefix = mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[sample_task_obj])
    mocker.patch('knowledge_manager.db.get_project_by_id', return_value=sample_project_for_task) # For resolving project_identifier
    mocker.patch('knowledge_manager.db.get_task_by_id', side_effect=lambda conn, tid: sample_task_obj if tid == sample_task_obj.id else None)


    found_task = task_ops.find_task(title_prefix, project_identifier=sample_project_for_task.id, base_data_dir=tmp_path)
    
    assert found_task is not None
    assert found_task.id == sample_task_obj.id
    mock_get_by_prefix.assert_called_once_with(mocker.ANY, title_prefix, project_id=sample_project_for_task.id)

def test_find_task_by_title_prefix_not_found(tmp_path: Path, mocker):
    title_prefix = "NonExistentPrefix"
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=None)
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[]) # No tasks match

    found_task = task_ops.find_task(title_prefix, base_data_dir=tmp_path)
    assert found_task is None

def test_find_task_by_title_prefix_ambiguous(tmp_path: Path, mocker, sample_task_obj: Task):
    title_prefix = "Ambig"
    task1 = Task(id=uuid.uuid4(), title="AmbigTask One", project_id=sample_task_obj.project_id)
    task2 = Task(id=uuid.uuid4(), title="AmbigTask Two", project_id=sample_task_obj.project_id)
    
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=None)
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[task1, task2])

    # find_task should return None if _resolve_task_id raises ValueError due to ambiguity
    found_task = task_ops.find_task(title_prefix, base_data_dir=tmp_path)
    assert found_task is None 
    # To test the specific error message, we'd need to call _resolve_task_id directly or check logs/stderr if CLI
    # For ops layer, returning None on resolution failure is one way to handle it.

def test_update_task_by_title_prefix_success(tmp_path: Path, mocker, sample_task_obj: Task):
    title_prefix = sample_task_obj.title[:7] # "Unique "
    new_title_for_update = "Super Updated Title"

    # Mock sequence for _resolve_task_id then db.get_task_by_id (for task object) then db.update_task
    mock_get_tasks_by_prefix = mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[sample_task_obj])
    # This mock is for db.get_task_by_id called *inside* update_task_details_and_status after resolution
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=sample_task_obj) 
    mock_db_update = mocker.patch('knowledge_manager.db.update_task', side_effect=mock_db_update_return_new_timestamped_task)

    updated_task = task_ops.update_task_details_and_status(
        task_identifier=title_prefix,
        new_title=new_title_for_update,
        base_data_dir=tmp_path
    )
    assert updated_task is not None
    assert updated_task.title == new_title_for_update
    mock_get_tasks_by_prefix.assert_called_once_with(mocker.ANY, title_prefix, project_id=None)
    mock_db_update.assert_called_once()

def test_update_task_by_title_prefix_ambiguous_fails(tmp_path: Path, mocker, sample_task_obj: Task):
    title_prefix = "AmbigUpdate"
    task1 = Task(id=uuid.uuid4(), title="AmbigUpdate One", project_id=sample_task_obj.project_id)
    task2 = Task(id=uuid.uuid4(), title="AmbigUpdate Two", project_id=sample_task_obj.project_id)
    
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[task1, task2])
    mock_db_update = mocker.patch('knowledge_manager.db.update_task')

    with pytest.raises(ValueError, match="Multiple tasks found"):
        task_ops.update_task_details_and_status(
            task_identifier=title_prefix,
            new_title="Does not matter",
            base_data_dir=tmp_path
        )
    mock_db_update.assert_not_called()


# --- Existing Tests for update_task_details_and_status, mark_task_status, etc. ---
# (Ensure these are still relevant or adapt them if their assumptions about ID only change)

def test_update_task_all_fields(tmp_path: Path, mocker, sample_task_obj: Task, sample_project_for_task: Project, another_project_for_task: Project):
    original_task_state = Task(**sample_task_obj.__dict__)
    # For find_task (which uses _resolve_task_id -> db.get_task_by_id for UUIDs)
    mocker.patch('knowledge_manager.db.get_task_by_id', side_effect=lambda conn, tid: original_task_state if tid == original_task_state.id else None)
    mocker.patch('knowledge_manager.db.update_task', side_effect=mock_db_update_return_new_timestamped_task)
    mocker.patch('knowledge_manager.db.get_project_by_id', side_effect=lambda conn, pid: another_project_for_task if pid == another_project_for_task.id else (sample_project_for_task if pid == sample_project_for_task.id else None))

    new_title = "Updated Task Title XYZ"; new_status = TaskStatus.IN_PROGRESS; new_priority = 1
    new_due_date_iso = "2026-01-01"; new_details_content = "Updated details ABC."
    
    updated_task = task_ops.update_task_details_and_status(
        task_identifier=original_task_state.id, new_title=new_title, new_status=new_status, new_priority=new_priority,
        new_due_date_iso=new_due_date_iso, new_details=new_details_content,
        new_project_identifier=another_project_for_task.id, base_data_dir=tmp_path
    )
    assert updated_task is not None; assert updated_task.title == new_title
    assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_only_title(tmp_path: Path, mocker, sample_task_obj: Task):
    original_task_state = Task(**sample_task_obj.__dict__)
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=original_task_state)
    mocker.patch('knowledge_manager.db.update_task', side_effect=mock_db_update_return_new_timestamped_task)
    new_title = "Only Title Updated"
    updated_task = task_ops.update_task_details_and_status(task_identifier=original_task_state.id, new_title=new_title, base_data_dir=tmp_path)
    assert updated_task.title == new_title; assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_clear_due_date_with_empty_string(tmp_path: Path, mocker, sample_task_obj: Task):
    original_task_state = Task(**sample_task_obj.__dict__); original_task_state.due_date = date(2025, 12, 12)
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=original_task_state)
    mocker.patch('knowledge_manager.db.update_task', side_effect=mock_db_update_return_new_timestamped_task)
    updated_task = task_ops.update_task_details_and_status(task_identifier=original_task_state.id, new_due_date_iso="", base_data_dir=tmp_path)
    assert updated_task.due_date is None; assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_clear_details_with_empty_string(tmp_path: Path, mocker, sample_task_obj: Task):
    original_task_state = Task(**sample_task_obj.__dict__)
    details_file = tmp_path / "files" / "tasks" / f"{original_task_state.id}.md"; details_file.parent.mkdir(parents=True, exist_ok=True)
    details_file.write_text("Original details", encoding="utf-8"); original_task_state.details_md_path = details_file
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=original_task_state)
    mocker.patch('knowledge_manager.db.update_task', side_effect=mock_db_update_return_new_timestamped_task)
    updated_task = task_ops.update_task_details_and_status(task_identifier=original_task_state.id, new_details="", base_data_dir=tmp_path)
    assert updated_task.details_md_path.read_text(encoding="utf-8") == ""; assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_clear_project(tmp_path: Path, mocker, sample_task_obj: Task, sample_project_for_task: Project):
    original_task_state = Task(**sample_task_obj.__dict__); assert original_task_state.project_id == sample_project_for_task.id 
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=original_task_state)
    mocker.patch('knowledge_manager.db.update_task', side_effect=mock_db_update_return_new_timestamped_task)
    updated_task = task_ops.update_task_details_and_status(task_identifier=original_task_state.id, clear_project=True, base_data_dir=tmp_path)
    assert updated_task.project_id is None; assert updated_task.modified_at > original_task_state.modified_at

def test_update_task_no_changes_provided(tmp_path: Path, mocker, sample_task_obj: Task):
    original_task_state = Task(**sample_task_obj.__dict__)
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=original_task_state)
    mock_db_update = mocker.patch('knowledge_manager.db.update_task')
    updated_task = task_ops.update_task_details_and_status(task_identifier=original_task_state.id, base_data_dir=tmp_path)
    assert updated_task == original_task_state; mock_db_update.assert_not_called()

def test_update_task_not_found(tmp_path: Path, mocker): # Corrected
    non_existent_id = uuid.uuid4()
    # _resolve_task_id will call db.get_task_by_id when task_identifier is a UUID
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=None) 
    mock_db_update = mocker.patch('knowledge_manager.db.update_task')
    
    # The error comes from _resolve_task_id when a UUID is not found
    with pytest.raises(ValueError, match=f"Task with ID '{non_existent_id}' not found."): 
        task_ops.update_task_details_and_status(
            task_identifier=non_existent_id, 
            new_title="New Title", 
            base_data_dir=tmp_path
        )
    mock_db_update.assert_not_called()

def test_update_task_set_done_updates_completed_at(tmp_path: Path, mocker, sample_task_obj: Task):
    sample_task_obj.status = TaskStatus.TODO; sample_task_obj.completed_at = None
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=sample_task_obj)
    def update_side_effect_for_done(conn, task_to_update):
        task_attrs = task_to_update.__dict__.copy()
        if task_attrs['status'] == TaskStatus.DONE and task_attrs['completed_at'] is None: task_attrs['completed_at'] = utils.get_current_utc_timestamp()
        elif task_attrs['status'] != TaskStatus.DONE: task_attrs['completed_at'] = None
        time.sleep(0.002); task_attrs['modified_at'] = utils.get_current_utc_timestamp()
        return Task(**task_attrs)
    mocker.patch('knowledge_manager.db.update_task', side_effect=update_side_effect_for_done)
    updated_task = task_ops.update_task_details_and_status(task_identifier=sample_task_obj.id, new_status=TaskStatus.DONE, base_data_dir=tmp_path)
    assert updated_task.status == TaskStatus.DONE; assert updated_task.completed_at is not None

# --- Tests for mark_task_status ---
def test_mark_task_status(tmp_path: Path, sample_task_obj: Task, mocker): # Corrected
    mock_update_details = mocker.patch('knowledge_manager.task_ops.update_task_details_and_status')
    returned_task_from_update = Task(**sample_task_obj.__dict__); returned_task_from_update.status = TaskStatus.IN_PROGRESS
    mock_update_details.return_value = returned_task_from_update
    
    result_task = task_ops.mark_task_status(
        sample_task_obj.id, 
        TaskStatus.IN_PROGRESS, 
        base_data_dir=tmp_path
        # project_identifier_context is None by default
    )
    
    mock_update_details.assert_called_once_with(
        task_identifier=sample_task_obj.id,
        new_status=TaskStatus.IN_PROGRESS,
        current_project_context_for_search=None, # Check this default
        base_data_dir=tmp_path
    )
    assert result_task.status == TaskStatus.IN_PROGRESS

# --- Tests for get_task_file_path ---
def test_get_task_file_path_task_exists_with_path(tmp_path: Path, sample_task_obj: Task, mocker):
    expected_path = tmp_path / "files" / "tasks" / f"{str(sample_task_obj.id)}.md"; sample_task_obj.details_md_path = expected_path
    mocker.patch('knowledge_manager.task_ops.find_task', return_value=sample_task_obj)
    returned_path = task_ops.get_task_file_path(task_identifier=sample_task_obj.id, base_data_dir=tmp_path)
    assert returned_path == expected_path

def test_get_task_file_path_task_not_found_raises_value_error(tmp_path: Path, mocker): # Renamed and corrected
    non_existent_id = uuid.uuid4()
    mocker.patch('knowledge_manager.task_ops.find_task', return_value=None)
    # Mock _resolve_task_id to simulate the error that find_task would catch and convert to None,
    # but get_task_file_path re-raises.
    mocker.patch('knowledge_manager.task_ops._resolve_task_id', side_effect=ValueError(f"For getpath: No task found with ID or title prefix '{non_existent_id}'."))

    with pytest.raises(ValueError, match=f"For getpath: No task found with ID or title prefix '{non_existent_id}'."):
        task_ops.get_task_file_path(task_identifier=non_existent_id, base_data_dir=tmp_path)


# --- Tests for delete_task_permanently ---
def test_delete_task_permanently_success_by_id(tmp_path: Path, mocker, sample_task_obj: Task): # Renamed for clarity
    details_path = tmp_path / "files" / "tasks" / f"{str(sample_task_obj.id)}.md"; sample_task_obj.details_md_path = details_path
    details_path.parent.mkdir(parents=True, exist_ok=True); details_path.write_text("Task details to delete", encoding="utf-8")
    
    # _resolve_task_id will call db.get_task_by_id, then delete_task_permanently calls it again
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=sample_task_obj)
    mock_db_delete = mocker.patch('knowledge_manager.db.delete_task', return_value=True)
    
    result = task_ops.delete_task_permanently(sample_task_obj.id, base_data_dir=tmp_path)
    assert result is True; assert not details_path.exists()
    mock_db_delete.assert_called_with(mocker.ANY, sample_task_obj.id)


def test_delete_task_permanently_by_title_prefix_success(tmp_path: Path, mocker, sample_task_obj: Task):
    title_prefix = sample_task_obj.title[:5]
    details_path = tmp_path / "files" / "tasks" / f"{str(sample_task_obj.id)}.md"; sample_task_obj.details_md_path = details_path
    details_path.parent.mkdir(parents=True, exist_ok=True); details_path.write_text("Task details to delete", encoding="utf-8")

    # _resolve_task_id will call db.get_tasks_by_title_prefix
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[sample_task_obj])
    # delete_task_permanently will then call db.get_task_by_id
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=sample_task_obj)
    mock_db_delete = mocker.patch('knowledge_manager.db.delete_task', return_value=True)

    result = task_ops.delete_task_permanently(title_prefix, base_data_dir=tmp_path)
    assert result is True
    assert not details_path.exists()
    mock_db_delete.assert_called_with(mocker.ANY, sample_task_obj.id)


def test_delete_task_permanently_task_not_found(tmp_path: Path, mocker):
    non_existent_id = uuid.uuid4()
    # _resolve_task_id will raise ValueError
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=None) 
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[])
    mock_db_delete = mocker.patch('knowledge_manager.db.delete_task')
    
    result = task_ops.delete_task_permanently(non_existent_id, base_data_dir=tmp_path)
    assert result is False # delete_task_permanently catches ValueError and returns False
    mock_db_delete.assert_not_called()

def test_find_task_by_title_prefix_correct_project_context(tmp_path: Path, mocker, sample_task_obj: Task, sample_project_for_task: Project):
    title_prefix = sample_task_obj.title[:5] 
    
    # Mock db.get_tasks_by_title_prefix to return the task ONLY when project_id matches
    def mock_get_by_prefix_with_proj_check(conn, prefix, project_id=None, limit=None):
        if prefix == title_prefix and project_id == sample_project_for_task.id:
            return [sample_task_obj]
        return []
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', side_effect=mock_get_by_prefix_with_proj_check)
    
    # Mock db.get_task_by_id for the final fetch after resolution
    mocker.patch('knowledge_manager.db.get_task_by_id', side_effect=lambda conn, tid: sample_task_obj if tid == sample_task_obj.id else None)
    # Mock project resolution for _resolve_project_id
    mocker.patch('knowledge_manager.db.get_project_by_id', return_value=sample_project_for_task)


    found_task = task_ops.find_task(
        title_prefix, 
        project_identifier=sample_project_for_task.id, # Provide correct project context
        base_data_dir=tmp_path
    )
    
    assert found_task is not None
    assert found_task.id == sample_task_obj.id
    # Check that get_tasks_by_title_prefix was called with the project_id
    db.get_tasks_by_title_prefix.assert_called_once_with(mocker.ANY, title_prefix, project_id=sample_project_for_task.id)

def test_find_task_by_title_prefix_wrong_project_context(tmp_path: Path, mocker, sample_task_obj: Task, sample_project_for_task: Project, another_project_for_task: Project):
    title_prefix = sample_task_obj.title[:5]
    
    # db.get_tasks_by_title_prefix should return empty if project_id doesn't match
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[])
    # Mock project resolution for _resolve_project_id
    mocker.patch('knowledge_manager.db.get_project_by_id', return_value=another_project_for_task)


    found_task = task_ops.find_task(
        title_prefix, 
        project_identifier=another_project_for_task.id, # Provide WRONG project context
        base_data_dir=tmp_path
    )
    
    assert found_task is None
    db.get_tasks_by_title_prefix.assert_called_once_with(mocker.ANY, title_prefix, project_id=another_project_for_task.id)

def test_find_task_by_title_prefix_ambiguous_within_project_context(tmp_path: Path, mocker, sample_project_for_task: Project):
    title_prefix = "SharedPrefix"
    task1_in_proj = Task(id=uuid.uuid4(), title="SharedPrefix Alpha", project_id=sample_project_for_task.id)
    task2_in_proj = Task(id=uuid.uuid4(), title="SharedPrefix Beta", project_id=sample_project_for_task.id)
    
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[task1_in_proj, task2_in_proj])
    mocker.patch('knowledge_manager.db.get_project_by_id', return_value=sample_project_for_task)

    # find_task returns None when _resolve_task_id raises ValueError due to ambiguity
    found_task = task_ops.find_task(
        title_prefix, 
        project_identifier=sample_project_for_task.id, 
        base_data_dir=tmp_path
    )
    assert found_task is None

def test_update_task_by_title_prefix_with_project_context(tmp_path: Path, mocker, sample_task_obj: Task, sample_project_for_task: Project):
    title_prefix = sample_task_obj.title[:7]
    new_title_for_update = "Contextual Update Success"

    # _resolve_task_id (via find_task logic in update) will call:
    # 1. db.get_project_by_id (for project_context)
    # 2. db.get_tasks_by_title_prefix (with project_id)
    # Then update_task_details_and_status calls db.get_task_by_id
    # Then db.update_task
    mocker.patch('knowledge_manager.db.get_project_by_id', return_value=sample_project_for_task)
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[sample_task_obj])
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=sample_task_obj)
    mock_db_update = mocker.patch('knowledge_manager.db.update_task', side_effect=mock_db_update_return_new_timestamped_task)

    updated_task = task_ops.update_task_details_and_status(
        task_identifier=title_prefix,
        new_title=new_title_for_update,
        current_project_context_for_search=sample_project_for_task.id, # Provide context
        base_data_dir=tmp_path
    )
    assert updated_task is not None
    assert updated_task.title == new_title_for_update
    db.get_tasks_by_title_prefix.assert_called_once_with(mocker.ANY, title_prefix, project_id=sample_project_for_task.id)
    mock_db_update.assert_called_once()

def test_mark_task_status_by_title_prefix_with_project_context(tmp_path: Path, mocker, sample_task_obj: Task, sample_project_for_task: Project):
    title_prefix = sample_task_obj.title[:6]
    sample_task_obj.status = TaskStatus.TODO # Ensure initial state

    # Mocks for mark_task_status -> update_task_details_and_status -> _resolve_task_id -> ...
    
    # Mock for _resolve_project_id when called with project name
    mocker.patch('knowledge_manager.db.get_project_by_name', return_value=sample_project_for_task) 
    # Mock for _resolve_project_id when called with project ID (fallback or direct)
    mocker.patch('knowledge_manager.db.get_project_by_id', return_value=sample_project_for_task) 

    # Mocks for _resolve_task_id
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[sample_task_obj])
    # This mock is for db.get_task_by_id called by _resolve_task_id (if identifier was UUID) 
    # AND by update_task_details_and_status after resolution
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=sample_task_obj) 
    
    # Mock the actual update_task in db layer
    def mock_db_update_for_status(conn, task_to_update: Task) -> Task:
        # Simulate the status change and timestamp updates
        task_attrs = task_to_update.__dict__.copy()
        task_attrs['status'] = TaskStatus.DONE
        task_attrs['completed_at'] = utils.get_current_utc_timestamp()
        time.sleep(0.001) # Ensure modified_at can be different
        task_attrs['modified_at'] = utils.get_current_utc_timestamp()
        return Task(**task_attrs)
    mocker.patch('knowledge_manager.db.update_task', side_effect=mock_db_update_for_status)

    updated_task = task_ops.mark_task_status(
        task_identifier=title_prefix,
        new_status=TaskStatus.DONE,
        project_identifier_context=sample_project_for_task.name, # Use name for context resolution
        base_data_dir=tmp_path
    )
    assert updated_task is not None
    assert updated_task.status == TaskStatus.DONE
    assert updated_task.completed_at is not None
    # Check that get_tasks_by_title_prefix was called correctly by _resolve_task_id
    db.get_tasks_by_title_prefix.assert_called_once_with(mocker.ANY, title_prefix, project_id=sample_project_for_task.id)
    # Check that get_project_by_name was called by _resolve_project_id
    db.get_project_by_name.assert_called_once_with(mocker.ANY, sample_project_for_task.name)

def test_get_task_file_path_by_title_prefix_with_project_context(tmp_path: Path, mocker, sample_task_obj: Task, sample_project_for_task: Project):
    title_prefix = sample_task_obj.title[:8]
    expected_path = tmp_path / "files" / "tasks" / f"{str(sample_task_obj.id)}.md"
    sample_task_obj.details_md_path = expected_path

    mocker.patch('knowledge_manager.db.get_project_by_id', return_value=sample_project_for_task)
    mocker.patch('knowledge_manager.db.get_tasks_by_title_prefix', return_value=[sample_task_obj])
    # find_task (called by get_task_file_path) will then call db.get_task_by_id
    mocker.patch('knowledge_manager.db.get_task_by_id', return_value=sample_task_obj)


    returned_path = task_ops.get_task_file_path(
        task_identifier=title_prefix,
        project_identifier_context=sample_project_for_task.id,
        base_data_dir=tmp_path
    )
    assert returned_path == expected_path
    db.get_tasks_by_title_prefix.assert_called_once_with(mocker.ANY, title_prefix, project_id=sample_project_for_task.id)

# End of File: tests/task_ops_test.py
