# File: knowledge_manager/task_ops.py
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Union
from datetime import date # For due_date

from . import db
from . import utils
from . import project_ops # For finding projects by identifier
from .models import Task, TaskStatus, Project

def _resolve_project_id(conn: db.sqlite3.Connection, project_identifier: Optional[Union[str, uuid.UUID]]) -> Optional[uuid.UUID]:
    """Helper to resolve a project identifier (name or UUID) to a project ID."""
    if not project_identifier:
        return None
    if isinstance(project_identifier, uuid.UUID):
        # Check if project exists if UUID is provided
        if db.get_project_by_id(conn, project_identifier):
            return project_identifier
        else:
            raise ValueError(f"Project with ID '{project_identifier}' not found.")
    
    # Assume string is a name
    project = db.get_project_by_name(conn, str(project_identifier))
    if project:
        return project.id
    else:
        # Try to interpret as UUID string if name lookup fails
        try:
            project_id_uuid = uuid.UUID(str(project_identifier))
            if db.get_project_by_id(conn, project_id_uuid):
                return project_id_uuid
        except ValueError:
            pass # Not a valid UUID string
        raise ValueError(f"Project with identifier '{project_identifier}' not found.")


def _resolve_task_id(conn: db.sqlite3.Connection, task_identifier: Optional[Union[str, uuid.UUID]]) -> Optional[uuid.UUID]:
    """Helper to resolve a task identifier (ID string or title prefix - simplified for now to ID) to a task ID."""
    if not task_identifier:
        return None
    if isinstance(task_identifier, uuid.UUID):
        if db.get_task_by_id(conn, task_identifier):
            return task_identifier
        else:
            raise ValueError(f"Task with ID '{task_identifier}' not found.")
    
    # For now, assume string identifier is a UUID string for tasks.
    # Title prefix search can be added later if needed.
    try:
        task_id_uuid = uuid.UUID(str(task_identifier))
        if db.get_task_by_id(conn, task_id_uuid):
            return task_id_uuid
        else:
            raise ValueError(f"Task with ID '{task_identifier}' not found.")
    except ValueError:
        raise ValueError(f"Invalid task identifier format: '{task_identifier}'. Expected UUID string.")


def create_new_task(
    title: str,
    project_identifier: Optional[Union[str, uuid.UUID]] = None,
    parent_task_identifier: Optional[Union[str, uuid.UUID]] = None,
    status: TaskStatus = TaskStatus.TODO,
    priority: int = 3,
    due_date_iso: Optional[str] = None, # YYYY-MM-DD string
    details: Optional[str] = None,
    base_data_dir: Optional[Path] = None
) -> Task:
    """
    Creates a new task, stores it in the database, and creates an
    associated Markdown file for its details if provided.
    """
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_project_id: Optional[uuid.UUID] = None
        if project_identifier:
            resolved_project_id = _resolve_project_id(conn, project_identifier)

        resolved_parent_task_id: Optional[uuid.UUID] = None
        if parent_task_identifier:
            resolved_parent_task_id = _resolve_task_id(conn, parent_task_identifier)
            # Optional: Check if parent task belongs to the same project if project_id is set
            if resolved_parent_task_id and resolved_project_id:
                parent_task_obj = db.get_task_by_id(conn, resolved_parent_task_id)
                if parent_task_obj and parent_task_obj.project_id != resolved_project_id:
                    raise ValueError("Parent task does not belong to the specified project.")


        task_id = uuid.uuid4()
        current_time = utils.get_current_utc_timestamp()
        
        md_path: Optional[Path] = None
        if details is not None:
            md_path = utils.generate_markdown_file_path(task_id, "task", base_data_dir)
            utils.write_markdown_file(md_path, details)

        parsed_due_date: Optional[date] = None
        if due_date_iso:
            try:
                parsed_due_date = date.fromisoformat(due_date_iso)
            except ValueError:
                raise ValueError(f"Invalid due_date format: '{due_date_iso}'. Expected YYYY-MM-DD.")

        task = Task(
            id=task_id,
            title=title,
            status=status,
            project_id=resolved_project_id,
            parent_task_id=resolved_parent_task_id,
            created_at=current_time,
            modified_at=current_time,
            priority=priority,
            due_date=parsed_due_date,
            details_md_path=md_path
        )
        
        added_task = db.add_task(conn, task)
        return added_task
    finally:
        if conn:
            conn.close()

def find_task(task_identifier: Union[str, uuid.UUID], base_data_dir: Optional[Path] = None) -> Optional[Task]:
    """
    Finds a task by its ID (string or UUID).
    Future: could be extended to search by title prefix.
    """
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        # _resolve_task_id already checks if task exists and raises ValueError if not or invalid format
        # So, if it returns a UUID, the task exists.
        try:
            resolved_id = _resolve_task_id(conn, task_identifier)
            if resolved_id: # Should always be true if no exception from _resolve_task_id
                 return db.get_task_by_id(conn, resolved_id)
            return None # Should not be reached if _resolve_task_id is correct
        except ValueError: # Raised by _resolve_task_id if not found or invalid format
            return None
    finally:
        if conn:
            conn.close()


def list_all_tasks(
    project_identifier: Optional[Union[str, uuid.UUID]] = None,
    status: Optional[TaskStatus] = None,
    parent_task_identifier: Optional[Union[str, uuid.UUID]] = None,
    include_subtasks_of_any_parent: bool = False, # Passed to db.list_tasks
    base_data_dir: Optional[Path] = None
) -> List[Task]:
    """Lists tasks with various filters."""
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_project_id: Optional[uuid.UUID] = None
        if project_identifier:
            resolved_project_id = _resolve_project_id(conn, project_identifier)

        resolved_parent_task_id: Optional[uuid.UUID] = None
        if parent_task_identifier:
             # Here, if parent_task_identifier is a name/prefix, it needs more complex resolution
             # For now, assume it's a UUID string for parent task ID.
            resolved_parent_task_id = _resolve_task_id(conn, parent_task_identifier)
            
        return db.list_tasks(
            conn,
            project_id=resolved_project_id,
            status=status,
            parent_task_id=resolved_parent_task_id,
            include_subtasks_of_any_parent=include_subtasks_of_any_parent
        )
    finally:
        if conn:
            conn.close()

def update_task_details_and_status(
    task_identifier: Union[str, uuid.UUID],
    new_title: Optional[str] = None,
    new_status: Optional[TaskStatus] = None,
    new_priority: Optional[int] = None,
    new_due_date_iso: Optional[str] = None, # Pass "" to clear, None to not change
    new_details: Optional[str] = None,      # Pass "" to clear, None to not change
    new_project_identifier: Optional[Union[str, uuid.UUID]] = None, # For moving task
    clear_project: bool = False, # To unassign from project
    base_data_dir: Optional[Path] = None
) -> Optional[Task]:
    """Updates various attributes of a task."""
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        task = find_task(task_identifier, base_data_dir=base_data_dir) # Uses its own connection
        if not task:
            return None

        updated = False
        if new_title is not None and task.title != new_title:
            task.title = new_title
            updated = True
        
        if new_status is not None and task.status != new_status:
            task.status = new_status
            updated = True
            if new_status == TaskStatus.DONE and task.completed_at is None:
                task.completed_at = utils.get_current_utc_timestamp()
            elif new_status != TaskStatus.DONE:
                task.completed_at = None # Clear if not done

        if new_priority is not None and task.priority != new_priority:
            task.priority = new_priority
            updated = True

        if new_due_date_iso is not None:
            if new_due_date_iso == "": # Clear due date
                if task.due_date is not None:
                    task.due_date = None
                    updated = True
            else:
                try:
                    parsed_due_date = date.fromisoformat(new_due_date_iso)
                    if task.due_date != parsed_due_date:
                        task.due_date = parsed_due_date
                        updated = True
                except ValueError:
                    raise ValueError(f"Invalid new_due_date format: '{new_due_date_iso}'. Expected YYYY-MM-DD.")
        
        if new_details is not None:
            if task.details_md_path is None and new_details: # Create if doesn't exist and details provided
                task.details_md_path = utils.generate_markdown_file_path(task.id, "task", base_data_dir)
            
            if task.details_md_path: # Path exists or was just created
                 utils.write_markdown_file(task.details_md_path, new_details)
            # If new_details is "" and path existed, file becomes empty.
            # If new_details is "" and path didn't exist, nothing happens unless we want to create empty file.
            # For simplicity, consider any call with new_details as an update intent.
            updated = True

        if clear_project:
            if task.project_id is not None:
                task.project_id = None
                updated = True
        elif new_project_identifier is not None:
            resolved_new_project_id = _resolve_project_id(conn, new_project_identifier)
            if task.project_id != resolved_new_project_id:
                task.project_id = resolved_new_project_id
                updated = True
        
        if updated:
            # db.update_task will set its own modified_at
            return db.update_task(conn, task) # Pass current connection
        else:
            return task
    finally:
        if conn:
            conn.close()

def mark_task_status(
    task_identifier: Union[str, uuid.UUID],
    new_status: TaskStatus,
    base_data_dir: Optional[Path] = None
) -> Optional[Task]:
    """Quickly marks a task with a new status."""
    return update_task_details_and_status(
        task_identifier=task_identifier,
        new_status=new_status,
        base_data_dir=base_data_dir
    )

def delete_task_permanently(
    task_identifier: Union[str, uuid.UUID],
    base_data_dir: Optional[Path] = None
) -> bool:
    """Deletes a task from DB and its Markdown file."""
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        # find_task uses its own connection, so we need to get the task object
        # using the current connection if we want to access its md_path before deletion.
        # Or, re-fetch using current connection.
        task_id_to_delete = _resolve_task_id(conn, task_identifier) # Ensures task exists
        if not task_id_to_delete: # Should not happen if _resolve_task_id raises error on not found
            return False 
            
        task_obj = db.get_task_by_id(conn, task_id_to_delete) # Fetch with current conn
        if not task_obj: # Should also not happen
            return False

        if task_obj.details_md_path and task_obj.details_md_path.exists():
            try:
                task_obj.details_md_path.unlink()
            except OSError:
                # Log error but proceed
                pass
        
        return db.delete_task(conn, task_obj.id)
    except ValueError: # From _resolve_task_id if task not found/invalid
        return False
    finally:
        if conn:
            conn.close()

# End of File: knowledge_manager/task_ops.py
