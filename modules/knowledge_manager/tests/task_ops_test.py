# File: tests/task_ops_test.py
import pytest
from unittest.mock import MagicMock, patch, call
import uuid
from pathlib import Path
from datetime import datetime, timezone, date
import sqlite3 # For type hinting and raising DB errors in mocks
import time 

from knowledge_manager import task_ops, utils
from knowledge_manager.models import Task, TaskStatus, Project, ProjectStatus

# --- Fixtures ---

@pytest.fixture
def mock_db_conn():
    """Fixture for a mocked database connection object."""
    return MagicMock(spec=sqlite3.Connection)

@pytest.fixture
def mock_task_ops_db_module(mocker, mock_db_conn):
    """Mocks functions in knowledge_manager.db module used by task_ops."""
    mock_get_conn = mocker.patch('knowledge_manager.db.get_db_connection', return_value=mock_db_conn)
    
    mock_add_task = mocker.patch('knowledge_manager.db.add_task')
    mock_get_task_by_id = mocker.patch('knowledge_manager.db.get_task_by_id')
    mock_list_tasks = mocker.patch('knowledge_manager.db.list_tasks')
    mock_update_task = mocker.patch('knowledge_manager.db.update_task')
    mock_delete_task = mocker.patch('knowledge_manager.db.delete_task')

    mock_get_project_by_id = mocker.patch('knowledge_manager.db.get_project_by_id')
    mock_get_project_by_name = mocker.patch('knowledge_manager.db.get_project_by_name')
    
    return {
        "get_db_connection": mock_get_conn,
        "db_conn_obj": mock_db_conn,
        "add_task": mock_add_task,
        "get_task_by_id": mock_get_task_by_id,
        "list_tasks": mock_list_tasks,
        "update_task": mock_update_task,
        "delete_task": mock_delete_task,
        "get_project_by_id": mock_get_project_by_id,
        "get_project_by_name": mock_get_project_by_name,
    }

@pytest.fixture
def sample_project_for_task(mock_task_ops_db_module) -> Project:
    project = Project(id=uuid.uuid4(), name="Task Project")
    mock_task_ops_db_module["get_project_by_id"].side_effect = lambda conn, pid: project if pid == project.id else None
    mock_task_ops_db_module["get_project_by_name"].side_effect = lambda conn, pname: project if pname == project.name else None
    return project


@pytest.fixture
def sample_parent_task_for_task(mock_task_ops_db_module, sample_project_for_task: Project) -> Task:
    parent_task = Task(id=uuid.uuid4(), title="Parent Task", project_id=sample_project_for_task.id)
    # More specific side effect for get_task_by_id for this fixture
    # It should only return this parent_task if its ID is queried.
    # If other tests need a general get_task_by_id, they should set their own specific side_effect.
    def specific_parent_lookup(conn, tid):
        if tid == parent_task.id:
            return parent_task
        return None # Or call a previously stored side_effect if chaining
    mock_task_ops_db_module["get_task_by_id"].side_effect = specific_parent_lookup
    return parent_task


@pytest.fixture
def sample_task_obj(sample_project_for_task: Project) -> Task:
    now = datetime.now(timezone.utc)
    return Task(
        id=uuid.uuid4(),
        title="Testable Task One",
        status=TaskStatus.TODO,
        project_id=sample_project_for_task.id,
        created_at=now,
        modified_at=now,
        priority=2,
        due_date=date(2025, 1, 10)
    )

# --- Tests for create_new_task ---

def test_create_new_task_success_basic(tmp_path: Path, mock_task_ops_db_module, sample_project_for_task: Project):
    task_title = "Basic New Task"
    mock_task_ops_db_module["add_task"].side_effect = lambda conn, t: t 

    created_task = task_ops.create_new_task(
        title=task_title,
        project_identifier=sample_project_for_task.id,
        base_data_dir=tmp_path
    )

    assert created_task.title == task_title
    assert created_task.project_id == sample_project_for_task.id
    assert created_task.details_md_path is None
    
    mock_task_ops_db_module["get_db_connection"].assert_called_once_with(tmp_path / utils.DB_FILE_NAME)
    # _resolve_project_id calls db.get_project_by_id when UUID is passed
    mock_task_ops_db_module["get_project_by_id"].assert_any_call(mock_task_ops_db_module["db_conn_obj"], sample_project_for_task.id)
    mock_task_ops_db_module["add_task"].assert_called_once()
    added_arg = mock_task_ops_db_module["add_task"].call_args[0][1]
    assert added_arg.title == task_title
    mock_task_ops_db_module["db_conn_obj"].close.assert_called_once()


def test_create_new_task_with_details_and_parent(
    tmp_path: Path, mock_task_ops_db_module, 
    sample_project_for_task: Project, sample_parent_task_for_task: Task
):
    task_title = "Detailed Subtask"
    details_content = "### Subtask Details\n- Point 1"
    due_date_str = "2025-07-15"
    sample_parent_task_for_task.project_id = sample_project_for_task.id

    # Ensure mocks are set up correctly for this specific test's needs
    mock_task_ops_db_module["get_project_by_name"].side_effect = lambda conn, pname: sample_project_for_task if pname == sample_project_for_task.name else None
    # get_task_by_id for parent task resolution (already set by sample_parent_task_for_task fixture)
    # If we need to resolve other tasks, this side_effect might need to be more general or reset
    # For this test, the fixture's side_effect for get_task_by_id is specific enough.
    
    mock_task_ops_db_module["add_task"].side_effect = lambda conn, t: t

    created_task = task_ops.create_new_task(
        title=task_title,
        project_identifier=sample_project_for_task.name,
        parent_task_identifier=sample_parent_task_for_task.id,
        details=details_content,
        due_date_iso=due_date_str,
        base_data_dir=tmp_path
    )

    assert created_task.title == task_title
    assert created_task.project_id == sample_project_for_task.id
    assert created_task.parent_task_id == sample_parent_task_for_task.id
    assert created_task.due_date == date(2025, 7, 15)
    assert created_task.details_md_path is not None
    assert created_task.details_md_path.read_text(encoding="utf-8") == details_content

    mock_task_ops_db_module["get_project_by_name"].assert_called_with(mock_task_ops_db_module["db_conn_obj"], sample_project_for_task.name)
    mock_task_ops_db_module["get_task_by_id"].assert_any_call(mock_task_ops_db_module["db_conn_obj"], sample_parent_task_for_task.id)


def test_create_new_task_project_not_found(tmp_path: Path, mock_task_ops_db_module):
    mock_task_ops_db_module["get_project_by_name"].return_value = None
    mock_task_ops_db_module["get_project_by_id"].return_value = None
    with pytest.raises(ValueError, match="Project with identifier 'NonExistentProject' not found."):
        task_ops.create_new_task(title="Task", project_identifier="NonExistentProject", base_data_dir=tmp_path)

def test_create_new_task_parent_task_not_found(tmp_path: Path, mock_task_ops_db_module, sample_project_for_task):
    mock_task_ops_db_module["get_project_by_id"].return_value = sample_project_for_task
    non_existent_parent_id = uuid.uuid4()
    # Ensure get_task_by_id specifically returns None for this ID
    mock_task_ops_db_module["get_task_by_id"].side_effect = lambda conn, tid: None if tid == non_existent_parent_id else (sample_parent_task_for_task if tid == sample_parent_task_for_task.id else None)


    with pytest.raises(ValueError, match=f"Task with ID '{non_existent_parent_id}' not found."):
        task_ops.create_new_task(
            title="Task", 
            project_identifier=sample_project_for_task.id,
            parent_task_identifier=non_existent_parent_id, 
            base_data_dir=tmp_path
        )

def test_create_new_task_parent_project_mismatch(
    tmp_path: Path, mock_task_ops_db_module, 
    sample_project_for_task: Project
):
    project1 = sample_project_for_task
    project2 = Project(id=uuid.uuid4(), name="Other Project For Task")
    parent_in_proj2 = Task(id=uuid.uuid4(), title="Parent in Proj2", project_id=project2.id)

    mock_task_ops_db_module["get_project_by_id"].side_effect = lambda conn, pid: project1 if pid == project1.id else (project2 if pid == project2.id else None)
    mock_task_ops_db_module["get_task_by_id"].return_value = parent_in_proj2

    with pytest.raises(ValueError, match="Parent task does not belong to the specified project."):
        task_ops.create_new_task(
            title="Subtask", project_identifier=project1.id,
            parent_task_identifier=parent_in_proj2.id, base_data_dir=tmp_path
        )

# --- Tests for find_task ---

def test_find_task_by_id_success(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    # Reset side_effect for get_task_by_id to be specific for this test
    mock_task_ops_db_module["get_task_by_id"].side_effect = lambda conn, tid: sample_task_obj if tid == sample_task_obj.id else None
    
    found_task = task_ops.find_task(sample_task_obj.id, base_data_dir=tmp_path)
    assert found_task == sample_task_obj
    mock_task_ops_db_module["get_task_by_id"].assert_any_call(mock_task_ops_db_module["db_conn_obj"], sample_task_obj.id)


def test_find_task_not_found(tmp_path: Path, mock_task_ops_db_module):
    non_existent_id = uuid.uuid4()
    mock_task_ops_db_module["get_task_by_id"].return_value = None
    
    found_task = task_ops.find_task(non_existent_id, base_data_dir=tmp_path)
    assert found_task is None

def test_find_task_invalid_identifier_format(tmp_path: Path, mock_task_ops_db_module):
    mock_task_ops_db_module["get_task_by_id"].return_value = None
    found_task = task_ops.find_task("not-a-uuid-string", base_data_dir=tmp_path)
    assert found_task is None


# --- Tests for list_all_tasks ---

def test_list_all_tasks_no_filters(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    mock_task_list = [sample_task_obj, Task(title="Another Task")]
    mock_task_ops_db_module["list_tasks"].return_value = mock_task_list

    tasks = task_ops.list_all_tasks(base_data_dir=tmp_path)
    assert tasks == mock_task_list
    mock_task_ops_db_module["list_tasks"].assert_called_once_with(
        mock_task_ops_db_module["db_conn_obj"],
        project_id=None, status=None, parent_task_id=None, include_subtasks_of_any_parent=False
    )

def test_list_all_tasks_with_project_filter(tmp_path: Path, mock_task_ops_db_module, sample_project_for_task: Project):
    # Reset get_project_by_id for this test's specific need
    mock_task_ops_db_module["get_project_by_id"].side_effect = lambda conn, pid: sample_project_for_task if pid == sample_project_for_task.id else None
    
    task_ops.list_all_tasks(project_identifier=sample_project_for_task.id, base_data_dir=tmp_path)
    mock_task_ops_db_module["list_tasks"].assert_called_once_with(
        mock_task_ops_db_module["db_conn_obj"],
        project_id=sample_project_for_task.id, status=None, parent_task_id=None, include_subtasks_of_any_parent=False
    )

# --- Tests for update_task_details_and_status ---
def test_update_task_all_fields(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, sample_project_for_task: Project):
    original_task_state = Task(**sample_task_obj.__dict__)
    # Mock for find_task (which uses _resolve_task_id -> db.get_task_by_id)
    mock_task_ops_db_module["get_task_by_id"].side_effect = lambda conn, tid: original_task_state if tid == original_task_state.id else None
    
    # Mock db.update_task to simulate timestamp update and return a new object
    def mock_db_update_task_side_effect(conn, task_passed_to_db: Task) -> Task:
        time.sleep(0.005) # Increased delay
        task_returned_by_db = Task(
            id=task_passed_to_db.id,
            title=task_passed_to_db.title,
            status=task_passed_to_db.status,
            project_id=task_passed_to_db.project_id,
            parent_task_id=task_passed_to_db.parent_task_id,
            created_at=task_passed_to_db.created_at,
            modified_at=utils.get_current_utc_timestamp(), # Fresh timestamp
            completed_at=task_passed_to_db.completed_at,
            priority=task_passed_to_db.priority,
            due_date=task_passed_to_db.due_date,
            details_md_path=task_passed_to_db.details_md_path
        )
        return task_returned_by_db
    mock_task_ops_db_module["update_task"].side_effect = mock_db_update_task_side_effect

    new_title = "Updated Task Title XYZ"
    new_status = TaskStatus.IN_PROGRESS
    new_priority = 1
    new_due_date_iso = "2026-01-01"
    new_details_content = "Updated details ABC."
    
    other_project = Project(id=uuid.uuid4(), name="Project Omega")
    # Mock for _resolve_project_id (used when new_project_identifier is passed)
    # Needs to find other_project by ID, and potentially sample_project_for_task if it were involved.
    def project_lookup_for_update(conn, pid):
        if pid == other_project.id: return other_project
        if pid == sample_project_for_task.id: return sample_project_for_task
        return None
    mock_task_ops_db_module["get_project_by_id"].side_effect = project_lookup_for_update


    updated_task = task_ops.update_task_details_and_status(
        task_identifier=original_task_state.id,
        new_title=new_title, new_status=new_status, new_priority=new_priority,
        new_due_date_iso=new_due_date_iso, new_details=new_details_content,
        new_project_identifier=other_project.id,
        base_data_dir=tmp_path
    )

    assert updated_task is not None
    assert updated_task.title == new_title
    assert updated_task.status == new_status
    assert updated_task.priority == new_priority
    assert updated_task.due_date == date(2026, 1, 1)
    assert updated_task.project_id == other_project.id
    assert updated_task.details_md_path is not None
    assert updated_task.details_md_path.read_text(encoding="utf-8") == new_details_content
    
    mock_task_ops_db_module["update_task"].assert_called_once()
    arg_passed_to_db_update = mock_task_ops_db_module["update_task"].call_args[0][1]
    assert arg_passed_to_db_update.title == new_title
    assert arg_passed_to_db_update.modified_at == original_task_state.modified_at # Before DB layer updates it

    assert updated_task.modified_at > original_task_state.modified_at, \
        f"New time {updated_task.modified_at} not greater than old time {original_task_state.modified_at}"


def test_update_task_set_done_updates_completed_at(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    sample_task_obj.status = TaskStatus.TODO
    sample_task_obj.completed_at = None
    mock_task_ops_db_module["get_task_by_id"].return_value = sample_task_obj # For find_task
    
    # Simulate db.update_task behavior
    def update_side_effect(conn, task_to_update):
        if task_to_update.status == TaskStatus.DONE and task_to_update.completed_at is None:
            task_to_update.completed_at = utils.get_current_utc_timestamp()
        elif task_to_update.status != TaskStatus.DONE:
            task_to_update.completed_at = None
        task_to_update.modified_at = utils.get_current_utc_timestamp()
        return task_to_update
    mock_task_ops_db_module["update_task"].side_effect = update_side_effect


    updated_task = task_ops.update_task_details_and_status(
        task_identifier=sample_task_obj.id, new_status=TaskStatus.DONE, base_data_dir=tmp_path
    )
    assert updated_task.status == TaskStatus.DONE
    assert updated_task.completed_at is not None
    assert isinstance(updated_task.completed_at, datetime)

def test_update_task_clear_due_date(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    sample_task_obj.due_date = date(2025,1,1)
    mock_task_ops_db_module["get_task_by_id"].return_value = sample_task_obj # For find_task
    mock_task_ops_db_module["update_task"].side_effect = lambda conn, t: t # Simple return for this test

    updated_task = task_ops.update_task_details_and_status(
        task_identifier=sample_task_obj.id, new_due_date_iso="", base_data_dir=tmp_path
    )
    assert updated_task.due_date is None

# --- Tests for mark_task_status ---
def test_mark_task_status(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task, mocker):
    mock_update_details = mocker.patch('knowledge_manager.task_ops.update_task_details_and_status')
    # Simulate it returns a task, can be the same obj or a new one
    returned_task_from_update = Task(**sample_task_obj.__dict__) 
    returned_task_from_update.status = TaskStatus.IN_PROGRESS # Reflect the change
    mock_update_details.return_value = returned_task_from_update

    result_task = task_ops.mark_task_status(sample_task_obj.id, TaskStatus.IN_PROGRESS, base_data_dir=tmp_path)

    mock_update_details.assert_called_once_with(
        task_identifier=sample_task_obj.id,
        new_status=TaskStatus.IN_PROGRESS,
        base_data_dir=tmp_path
    )
    assert result_task.status == TaskStatus.IN_PROGRESS


# --- Tests for delete_task_permanently ---
def test_delete_task_permanently_success(tmp_path: Path, mock_task_ops_db_module, sample_task_obj: Task):
    details_path = tmp_path / "files" / "tasks" / f"{str(sample_task_obj.id)}.md"
    sample_task_obj.details_md_path = details_path
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.write_text("Task details to delete", encoding="utf-8")
    
    mock_task_ops_db_module["get_task_by_id"].return_value = sample_task_obj # For _resolve_task_id and subsequent get
    mock_task_ops_db_module["delete_task"].return_value = True

    result = task_ops.delete_task_permanently(sample_task_obj.id, base_data_dir=tmp_path)

    assert result is True
    assert not details_path.exists()
    mock_task_ops_db_module["delete_task"].assert_called_with(mock_task_ops_db_module["db_conn_obj"], sample_task_obj.id)

def test_delete_task_permanently_task_not_found(tmp_path: Path, mock_task_ops_db_module):
    non_existent_id = uuid.uuid4()
    mock_task_ops_db_module["get_task_by_id"].return_value = None 
    
    result = task_ops.delete_task_permanently(non_existent_id, base_data_dir=tmp_path)
    assert result is False
    mock_task_ops_db_module["delete_task"].assert_not_called()

# End of File: tests/task_ops_test.py
