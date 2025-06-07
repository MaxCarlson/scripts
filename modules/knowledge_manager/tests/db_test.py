# File: tests/db_test.py
import sqlite3
import pytest
import uuid
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
import time 

# Adjust the import path based on your project structure.
from knowledge_manager.db import (
    init_db, 
    get_db_connection,
    add_project, get_project_by_id, get_project_by_name, list_projects, update_project, delete_project,
    add_task, get_task_by_id, list_tasks, update_task, delete_task,
    get_tasks_by_title_prefix 
)
from knowledge_manager.models import Project, ProjectStatus, Task, TaskStatus

# --- (The rest of YOUR file that you provided, starting from @pytest.fixture def temp_db_path...) ---
# ALL YOUR EXISTING FIXTURES AND TESTS BELOW THIS LINE REMAIN UNCHANGED.
# I will not repeat them here to keep the response focused on the fix.
# The new tests for get_tasks_by_title_prefix that you added at the end
# of your file are correct and should now work with these imports.

@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """
    Pytest fixture to create a temporary database file path for testing.
    The database file itself is not created by this fixture, only its path.
    """
    return tmp_path / "test_km.db"

@pytest.fixture
def db_conn(temp_db_path: Path) -> sqlite3.Connection:
    """
    Pytest fixture to initialize the database and provide a connection.
    The connection is closed automatically after the test.
    """
    init_db(temp_db_path) # Ensure schema is created
    conn = get_db_connection(temp_db_path)
    yield conn # Provide the connection to the test
    conn.close() # Teardown: close the connection

# --- Schema Initialization Tests (Existing) ---

def test_init_db_creates_database_file(temp_db_path: Path):
    assert not temp_db_path.exists()
    init_db(temp_db_path)
    assert temp_db_path.exists()

def test_init_db_creates_tables(db_conn: sqlite3.Connection): # Uses db_conn fixture
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projects';")
    assert cursor.fetchone() is not None, "Table 'projects' was not created."
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
    assert cursor.fetchone() is not None, "Table 'tasks' was not created."

def test_init_db_projects_table_schema(db_conn: sqlite3.Connection):
    cursor = db_conn.cursor()
    cursor.execute("PRAGMA table_info(projects);")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    expected_columns = {
        "id": "TEXT", "name": "TEXT", "status": "TEXT",
        "created_at": "TEXT", "modified_at": "TEXT", "description_md_path": "TEXT"
    }
    for col_name, col_type in expected_columns.items():
        assert col_name in columns
        assert columns[col_name].upper() == col_type.upper()

def test_init_db_tasks_table_schema(db_conn: sqlite3.Connection):
    cursor = db_conn.cursor()
    cursor.execute("PRAGMA table_info(tasks);")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    expected_columns = {
        "id": "TEXT", "title": "TEXT", "status": "TEXT",
        "project_id": "TEXT", "parent_task_id": "TEXT",
        "created_at": "TEXT", "modified_at": "TEXT", "completed_at": "TEXT",
        "priority": "INTEGER", "due_date": "TEXT", "details_md_path": "TEXT"
    }
    for col_name, col_type in expected_columns.items():
        assert col_name in columns
        assert columns[col_name].upper() == col_type.upper()
    cursor.execute("PRAGMA foreign_key_list(tasks);")
    fk_info = cursor.fetchall()
    project_fk_found = any(row[2] == 'projects' and row[3] == 'project_id' and row[4] == 'id' for row in fk_info)
    task_fk_found = any(row[2] == 'tasks' and row[3] == 'parent_task_id' and row[4] == 'id' for row in fk_info)
    assert project_fk_found
    assert task_fk_found

# --- Project CRUD Tests ---

@pytest.fixture
def sample_project() -> Project:
    return Project(name="Test Project Alpha", status=ProjectStatus.ACTIVE, description_md_path=Path("desc.md"))

def test_add_project(db_conn: sqlite3.Connection, sample_project: Project):
    added_project = add_project(db_conn, sample_project)
    assert added_project.id == sample_project.id
    assert added_project.name == sample_project.name
    assert added_project.status == sample_project.status
    assert added_project.description_md_path == sample_project.description_md_path
    assert isinstance(added_project.created_at, datetime)
    assert isinstance(added_project.modified_at, datetime)
    assert added_project.modified_at >= added_project.created_at

    # Verify it's in the DB
    retrieved = get_project_by_id(db_conn, added_project.id)
    assert retrieved is not None
    assert retrieved.name == sample_project.name

def test_get_project_by_id(db_conn: sqlite3.Connection, sample_project: Project):
    add_project(db_conn, sample_project)
    retrieved = get_project_by_id(db_conn, sample_project.id)
    assert retrieved is not None
    assert retrieved.id == sample_project.id
    assert retrieved.name == sample_project.name
    assert retrieved.status == sample_project.status
    assert retrieved.description_md_path == sample_project.description_md_path

def test_get_project_by_id_not_found(db_conn: sqlite3.Connection):
    non_existent_id = uuid.uuid4()
    retrieved = get_project_by_id(db_conn, non_existent_id)
    assert retrieved is None

def test_get_project_by_name(db_conn: sqlite3.Connection, sample_project: Project):
    add_project(db_conn, sample_project)
    retrieved = get_project_by_name(db_conn, sample_project.name)
    assert retrieved is not None
    assert retrieved.id == sample_project.id
    assert retrieved.name == sample_project.name

def test_get_project_by_name_not_found(db_conn: sqlite3.Connection):
    retrieved = get_project_by_name(db_conn, "Non Existent Project Name")
    assert retrieved is None

def test_list_projects(db_conn: sqlite3.Connection):
    proj1 = Project(name="Project Apple", status=ProjectStatus.ACTIVE)
    proj2 = Project(name="Project Banana", status=ProjectStatus.BACKLOG)
    proj3 = Project(name="Project Cherry", status=ProjectStatus.ACTIVE)
    add_project(db_conn, proj1)
    add_project(db_conn, proj2)
    add_project(db_conn, proj3)

    all_projects = list_projects(db_conn)
    assert len(all_projects) == 3
    assert all_projects[0].name == "Project Apple" # Sorted by name
    assert all_projects[1].name == "Project Banana"
    assert all_projects[2].name == "Project Cherry"

    active_projects = list_projects(db_conn, status=ProjectStatus.ACTIVE)
    assert len(active_projects) == 2
    assert all(p.status == ProjectStatus.ACTIVE for p in active_projects)
    assert "Project Apple" in [p.name for p in active_projects]
    assert "Project Cherry" in [p.name for p in active_projects]

    backlog_projects = list_projects(db_conn, status=ProjectStatus.BACKLOG)
    assert len(backlog_projects) == 1
    assert backlog_projects[0].name == "Project Banana"

def test_update_project(db_conn: sqlite3.Connection, sample_project: Project):
    add_project(db_conn, sample_project)
    
    original_modified_at = get_project_by_id(db_conn, sample_project.id).modified_at

    sample_project.name = "Updated Project Alpha"
    sample_project.status = ProjectStatus.COMPLETED
    sample_project.description_md_path = Path("new_desc.md")
    
    # Ensure a small delay so modified_at is observably different
    import time; time.sleep(0.01) 

    updated_project = update_project(db_conn, sample_project)
    assert updated_project is not None
    assert updated_project.name == "Updated Project Alpha"
    assert updated_project.status == ProjectStatus.COMPLETED
    assert updated_project.description_md_path == Path("new_desc.md")
    assert updated_project.modified_at > original_modified_at

    retrieved = get_project_by_id(db_conn, sample_project.id)
    assert retrieved.name == "Updated Project Alpha"
    assert retrieved.status == ProjectStatus.COMPLETED

def test_update_project_not_found(db_conn: sqlite3.Connection):
    non_existent_project = Project(id=uuid.uuid4(), name="Ghost Project")
    result = update_project(db_conn, non_existent_project)
    assert result is None

def test_delete_project(db_conn: sqlite3.Connection, sample_project: Project):
    add_project(db_conn, sample_project)
    assert get_project_by_id(db_conn, sample_project.id) is not None
    
    result = delete_project(db_conn, sample_project.id)
    assert result is True
    assert get_project_by_id(db_conn, sample_project.id) is None

def test_delete_project_not_found(db_conn: sqlite3.Connection):
    non_existent_id = uuid.uuid4()
    result = delete_project(db_conn, non_existent_id)
    assert result is False

# --- Task CRUD Tests ---

@pytest.fixture
def sample_task(sample_project: Project) -> Task: # Depends on sample_project for project_id
    return Task(
        title="Test Task Alpha", 
        status=TaskStatus.TODO,
        project_id=sample_project.id, # Link to the sample project
        priority=1,
        due_date=date(2024, 12, 31),
        details_md_path=Path("task_details.md")
    )

def test_add_task(db_conn: sqlite3.Connection, sample_project: Project, sample_task: Task):
    # First, add the project sample_task depends on
    add_project(db_conn, sample_project)
    
    added_task = add_task(db_conn, sample_task)
    assert added_task.id == sample_task.id
    assert added_task.title == sample_task.title
    assert added_task.status == sample_task.status
    assert added_task.project_id == sample_project.id
    assert added_task.priority == sample_task.priority
    assert added_task.due_date == sample_task.due_date
    assert added_task.details_md_path == sample_task.details_md_path
    assert isinstance(added_task.created_at, datetime)
    assert isinstance(added_task.modified_at, datetime)

    retrieved = get_task_by_id(db_conn, added_task.id)
    assert retrieved is not None
    assert retrieved.title == sample_task.title

def test_add_task_with_parent(db_conn: sqlite3.Connection, sample_project: Project):
    add_project(db_conn, sample_project)
    parent_task_obj = Task(title="Parent Task", project_id=sample_project.id)
    add_task(db_conn, parent_task_obj)

    sub_task_obj = Task(title="Sub Task", project_id=sample_project.id, parent_task_id=parent_task_obj.id)
    added_sub_task = add_task(db_conn, sub_task_obj)
    
    retrieved = get_task_by_id(db_conn, added_sub_task.id)
    assert retrieved is not None
    assert retrieved.parent_task_id == parent_task_obj.id

def test_get_task_by_id(db_conn: sqlite3.Connection, sample_project: Project, sample_task: Task):
    add_project(db_conn, sample_project)
    add_task(db_conn, sample_task)
    
    retrieved = get_task_by_id(db_conn, sample_task.id)
    assert retrieved is not None
    assert retrieved.id == sample_task.id
    assert retrieved.title == sample_task.title
    assert retrieved.project_id == sample_project.id

def test_get_task_by_id_not_found(db_conn: sqlite3.Connection):
    non_existent_id = uuid.uuid4()
    retrieved = get_task_by_id(db_conn, non_existent_id)
    assert retrieved is None

def test_list_tasks(db_conn: sqlite3.Connection, sample_project: Project):
    add_project(db_conn, sample_project)
    
    task1 = Task(title="Task A (Proj1, P1)", project_id=sample_project.id, priority=1, status=TaskStatus.TODO)
    task2 = Task(title="Task B (Proj1, P2, Done)", project_id=sample_project.id, priority=2, status=TaskStatus.DONE)
    task3 = Task(title="Task C (Proj1, P1, IP)", project_id=sample_project.id, priority=1, status=TaskStatus.IN_PROGRESS)
    # Task for another project (or no project)
    other_project = Project(name="Other Project")
    add_project(db_conn, other_project)
    task4 = Task(title="Task D (OtherProj)", project_id=other_project.id, priority=3)

    add_task(db_conn, task1)
    add_task(db_conn, task2)
    add_task(db_conn, task3)
    add_task(db_conn, task4)

    # List all tasks for sample_project
    proj_tasks = list_tasks(db_conn, project_id=sample_project.id, include_subtasks_of_any_parent=True)
    assert len(proj_tasks) == 3
    # Check order: done is last, then priority, then created_at
    assert proj_tasks[0].title == task1.title
    assert proj_tasks[1].title == task3.title
    assert proj_tasks[2].title == task2.title

    # List TODO tasks for sample_project
    todo_proj_tasks = list_tasks(db_conn, project_id=sample_project.id, status_filter=[TaskStatus.TODO], include_subtasks_of_any_parent=True)
    assert len(todo_proj_tasks) == 1
    assert todo_proj_tasks[0].title == task1.title

    # List all tasks (across all projects)
    all_tasks_ever = list_tasks(db_conn, include_subtasks_of_any_parent=True)
    assert len(all_tasks_ever) == 4
    
    # List top-level tasks for sample_project (default behavior for parent_task_id=None)
    top_level_tasks = list_tasks(db_conn, project_id=sample_project.id)
    assert len(top_level_tasks) == 3 # All current tasks are top-level

def test_list_sub_tasks(db_conn: sqlite3.Connection, sample_project: Project):
    add_project(db_conn, sample_project)
    parent = Task(title="Parent", project_id=sample_project.id)
    add_task(db_conn, parent)
    sub1 = Task(title="Sub1", project_id=sample_project.id, parent_task_id=parent.id)
    add_task(db_conn, sub1)
    sub2 = Task(title="Sub2", project_id=sample_project.id, parent_task_id=parent.id)
    add_task(db_conn, sub2)
    # Another top-level task
    other_top = Task(title="Other Top", project_id=sample_project.id)
    add_task(db_conn, other_top)

    subs_of_parent = list_tasks(db_conn, parent_task_id=parent.id)
    assert len(subs_of_parent) == 2
    assert {t.title for t in subs_of_parent} == {"Sub1", "Sub2"}

    top_level_tasks = list_tasks(db_conn, project_id=sample_project.id) # parent_task_id is None, include_subtasks_of_any_parent=False
    assert len(top_level_tasks) == 2
    assert {t.title for t in top_level_tasks} == {"Parent", "Other Top"}


def test_update_task(db_conn: sqlite3.Connection, sample_project: Project, sample_task: Task):
    add_project(db_conn, sample_project)
    add_task(db_conn, sample_task)

    original_modified_at = get_task_by_id(db_conn, sample_task.id).modified_at

    sample_task.title = "Updated Test Task Alpha"
    sample_task.status = TaskStatus.IN_PROGRESS
    sample_task.priority = 2
    new_due_date = date(2025, 1, 15)
    sample_task.due_date = new_due_date
    
    import time; time.sleep(0.01) # Ensure modified_at changes

    updated_task = update_task(db_conn, sample_task)
    assert updated_task is not None
    assert updated_task.title == "Updated Test Task Alpha"
    assert updated_task.status == TaskStatus.IN_PROGRESS
    assert updated_task.priority == 2
    assert updated_task.due_date == new_due_date
    assert updated_task.modified_at > original_modified_at
    assert updated_task.completed_at is None # Should be None if not DONE

    retrieved = get_task_by_id(db_conn, sample_task.id)
    assert retrieved.title == "Updated Test Task Alpha"
    assert retrieved.status == TaskStatus.IN_PROGRESS

def test_update_task_to_done_sets_completed_at(db_conn: sqlite3.Connection, sample_project: Project, sample_task: Task):
    add_project(db_conn, sample_project)
    sample_task.status = TaskStatus.TODO # Ensure it's not done initially
    sample_task.completed_at = None
    add_task(db_conn, sample_task)

    sample_task.status = TaskStatus.DONE
    updated_task = update_task(db_conn, sample_task)
    
    assert updated_task is not None
    assert updated_task.status == TaskStatus.DONE
    assert updated_task.completed_at is not None
    assert isinstance(updated_task.completed_at, datetime)
    # Check it's recent
    assert (datetime.now(timezone.utc) - updated_task.completed_at).total_seconds() < 5 

    # Check if changing from DONE clears completed_at
    updated_task.status = TaskStatus.TODO
    re_updated_task = update_task(db_conn, updated_task)
    assert re_updated_task.completed_at is None


def test_update_task_not_found(db_conn: sqlite3.Connection):
    non_existent_task = Task(id=uuid.uuid4(), title="Ghost Task")
    result = update_task(db_conn, non_existent_task)
    assert result is None

def test_delete_task(db_conn: sqlite3.Connection, sample_project: Project, sample_task: Task):
    add_project(db_conn, sample_project)
    add_task(db_conn, sample_task)
    assert get_task_by_id(db_conn, sample_task.id) is not None
    
    result = delete_task(db_conn, sample_task.id)
    assert result is True
    assert get_task_by_id(db_conn, sample_task.id) is None

def test_delete_task_not_found(db_conn: sqlite3.Connection):
    non_existent_id = uuid.uuid4()
    result = delete_task(db_conn, non_existent_id)
    assert result is False

def test_delete_project_unlinks_tasks(db_conn: sqlite3.Connection, sample_project: Project, sample_task: Task):
    """ Test ON DELETE SET NULL for project_id in tasks table """
    add_project(db_conn, sample_project)
    sample_task.project_id = sample_project.id
    add_task(db_conn, sample_task)

    retrieved_task = get_task_by_id(db_conn, sample_task.id)
    assert retrieved_task.project_id == sample_project.id

    delete_project(db_conn, sample_project.id) # Delete the project

    # Task should still exist but its project_id should be NULL
    task_after_proj_delete = get_task_by_id(db_conn, sample_task.id)
    assert task_after_proj_delete is not None
    assert task_after_proj_delete.project_id is None

def test_delete_parent_task_cascades_to_subtasks(db_conn: sqlite3.Connection, sample_project: Project):
    """ Test ON DELETE CASCADE for parent_task_id in tasks table """
    add_project(db_conn, sample_project)
    parent = Task(title="Parent Task to Delete", project_id=sample_project.id)
    add_task(db_conn, parent)
    subtask = Task(title="Subtask to be Cascaded", project_id=sample_project.id, parent_task_id=parent.id)
    add_task(db_conn, subtask)

    assert get_task_by_id(db_conn, parent.id) is not None
    assert get_task_by_id(db_conn, subtask.id) is not None

    delete_task(db_conn, parent.id) # Delete the parent task

    assert get_task_by_id(db_conn, parent.id) is None
    assert get_task_by_id(db_conn, subtask.id) is None # Subtask should also be deleted

def test_get_tasks_by_title_prefix_no_match(db_conn: sqlite3.Connection):
    # Add some tasks first
    proj = Project(name="Test Project for Prefix")
    add_project(db_conn, proj)
    task1 = Task(title="Alpha Task", project_id=proj.id)
    task2 = Task(title="Beta Task", project_id=proj.id)
    add_task(db_conn, task1)
    add_task(db_conn, task2)

    tasks = get_tasks_by_title_prefix(db_conn, "Gamma")
    assert len(tasks) == 0

def test_get_tasks_by_title_prefix_exact_match_one(db_conn: sqlite3.Connection):
    proj = Project(name="Test Project for Prefix")
    add_project(db_conn, proj)
    task1 = Task(title="UniqueTitleTask", project_id=proj.id)
    add_task(db_conn, task1)
    add_task(db_conn, Task(title="Another Task", project_id=proj.id))

    tasks = get_tasks_by_title_prefix(db_conn, "UniqueTitleTask")
    assert len(tasks) == 1
    assert tasks[0].id == task1.id
    assert tasks[0].title == "UniqueTitleTask"

def test_get_tasks_by_title_prefix_case_insensitive(db_conn: sqlite3.Connection):
    proj = Project(name="Test Project for Prefix")
    add_project(db_conn, proj)
    task1 = Task(title="CaseSensitiveTask", project_id=proj.id)
    add_task(db_conn, task1)

    tasks_lower = get_tasks_by_title_prefix(db_conn, "casesensitive")
    assert len(tasks_lower) == 1
    assert tasks_lower[0].id == task1.id

    tasks_upper = get_tasks_by_title_prefix(db_conn, "CASESENSITIVE")
    assert len(tasks_upper) == 1
    assert tasks_upper[0].id == task1.id

    tasks_mixed = get_tasks_by_title_prefix(db_conn, "CaSeSeNsItIvE")
    assert len(tasks_mixed) == 1
    assert tasks_mixed[0].id == task1.id

def test_get_tasks_by_title_prefix_with_project_filter(db_conn: sqlite3.Connection):
    proj1 = Project(name="Project One")
    proj2 = Project(name="Project Two")
    add_project(db_conn, proj1)
    add_project(db_conn, proj2)

    task1_p1 = Task(title="CommonPrefix Task", project_id=proj1.id)
    task2_p1 = Task(title="CommonPrefix Another", project_id=proj1.id)
    task1_p2 = Task(title="CommonPrefix Task In P2", project_id=proj2.id)
    add_task(db_conn, task1_p1)
    add_task(db_conn, task2_p1)
    add_task(db_conn, task1_p2)

    # Search in Project One
    tasks_p1 = get_tasks_by_title_prefix(db_conn, "CommonPrefix", project_id=proj1.id)
    assert len(tasks_p1) == 2
    assert {t.id for t in tasks_p1} == {task1_p1.id, task2_p1.id}

    # Search in Project Two
    tasks_p2 = get_tasks_by_title_prefix(db_conn, "CommonPrefix", project_id=proj2.id)
    assert len(tasks_p2) == 1
    assert tasks_p2[0].id == task1_p2.id

    # Search without project filter (should find all 3)
    tasks_all = get_tasks_by_title_prefix(db_conn, "CommonPrefix")
    assert len(tasks_all) == 3


def test_get_tasks_by_title_prefix_empty_prefix(db_conn: sqlite3.Connection):
    # An empty prefix should match all tasks (LIKE '%')
    proj = Project(name="Test Project for Empty Prefix")
    add_project(db_conn, proj)
    task1 = Task(title="Task One", project_id=proj.id)
    task2 = Task(title="Task Two", project_id=proj.id)
    add_task(db_conn, task1)
    add_task(db_conn, task2)

    tasks = get_tasks_by_title_prefix(db_conn, "")
    assert len(tasks) == 2 # Should return all tasks, ordered by created_at DESC

def test_get_tasks_by_title_prefix_partial_match_multiple(db_conn: sqlite3.Connection):
    proj = Project(name="Test Project for Prefix"); add_project(db_conn, proj)
    
    base_date = date(2023, 1, 1)
    
    task3_created_at = datetime.combine(base_date, datetime.min.time(), tzinfo=timezone.utc)
    task2_created_at = datetime.combine(base_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    task1_created_at = datetime.combine(base_date + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc) # Newest

    task1 = Task(title="SearchMe One", project_id=proj.id, created_at=task1_created_at)
    task2 = Task(title="SearchMe Two", project_id=proj.id, created_at=task2_created_at)
    task3 = Task(title="Different Task", project_id=proj.id, created_at=task3_created_at)
    
    add_task(db_conn, task3) 
    add_task(db_conn, task1) 
    add_task(db_conn, task2) 

    tasks = get_tasks_by_title_prefix(db_conn, "SearchMe")
    assert len(tasks) == 2
    assert tasks[0].id == task1.id
    assert tasks[1].id == task2.id
    assert task3.id not in [t.id for t in tasks]

def test_get_tasks_by_title_prefix_with_limit(db_conn: sqlite3.Connection):
    proj = Project(name="Test Project for Limit"); add_project(db_conn, proj)

    base_date = date(2023, 1, 1)
    task3_ct = datetime.combine(base_date, datetime.min.time(), tzinfo=timezone.utc) # Oldest
    task2_ct = datetime.combine(base_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    task1_ct = datetime.combine(base_date + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc) # Newest

    task1 = Task(title="LimitTest A", project_id=proj.id, created_at=task1_ct) 
    task2 = Task(title="LimitTest B", project_id=proj.id, created_at=task2_ct)
    task3 = Task(title="LimitTest C", project_id=proj.id, created_at=task3_ct) 
    
    add_task(db_conn, task3)
    add_task(db_conn, task2)
    add_task(db_conn, task1)

    tasks = get_tasks_by_title_prefix(db_conn, "LimitTest", limit=2)
    assert len(tasks) == 2
    assert tasks[0].id == task1.id
    assert tasks[1].id == task2.id
