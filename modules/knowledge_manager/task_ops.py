# File: knowledge_manager/task_ops.py
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Union
from datetime import date, datetime, timezone # Added datetime, timezone for completed_at

from . import db
from . import utils
# from . import project_ops # Not strictly needed if resolving project IDs via db layer
from .models import Task, TaskStatus, Project # Project needed for type hints if returning it

def _resolve_project_id(conn: db.sqlite3.Connection, project_identifier: Optional[Union[str, uuid.UUID]]) -> Optional[uuid.UUID]:
    """Helper to resolve a project identifier (name or UUID) to a project ID."""
    if not project_identifier:
        return None
    if isinstance(project_identifier, uuid.UUID):
        project_obj = db.get_project_by_id(conn, project_identifier)
        if project_obj:
            return project_identifier
        else:
            raise ValueError(f"Project with ID '{project_identifier}' not found.")
    
    project_obj = db.get_project_by_name(conn, str(project_identifier))
    if project_obj:
        return project_obj.id
    else:
        try:
            project_id_uuid = uuid.UUID(str(project_identifier))
            project_obj_by_uuid = db.get_project_by_id(conn, project_id_uuid)
            if project_obj_by_uuid:
                return project_id_uuid
        except ValueError:
            pass 
        raise ValueError(f"Project with identifier '{project_identifier}' not found.")


def _resolve_task_id(conn: db.sqlite3.Connection, task_identifier: Optional[Union[str, uuid.UUID]]) -> Optional[uuid.UUID]:
    """Helper to resolve a task identifier (ID string or UUID) to a task ID."""
    if not task_identifier:
        return None
    if isinstance(task_identifier, uuid.UUID):
        task_obj = db.get_task_by_id(conn, task_identifier)
        if task_obj:
            return task_identifier
        else:
            raise ValueError(f"Task with ID '{task_identifier}' not found.")
    
    try:
        task_id_uuid = uuid.UUID(str(task_identifier))
        task_obj_by_uuid = db.get_task_by_id(conn, task_id_uuid)
        if task_obj_by_uuid:
            return task_id_uuid
        else: # Valid UUID format, but not found
            raise ValueError(f"Task with ID '{task_identifier}' not found.")
    except ValueError: # Handles both invalid UUID format and not found from above
        raise ValueError(f"Invalid task identifier or task not found: '{task_identifier}'. Expected UUID string.")


def create_new_task(
    title: str,
    project_identifier: Optional[Union[str, uuid.UUID]] = None,
    parent_task_identifier: Optional[Union[str, uuid.UUID]] = None,
    status: TaskStatus = TaskStatus.TODO,
    priority: int = 3,
    due_date_iso: Optional[str] = None, 
    details: Optional[str] = None,
    base_data_dir: Optional[Path] = None
) -> Task:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_project_id: Optional[uuid.UUID] = None
        if project_identifier:
            resolved_project_id = _resolve_project_id(conn, project_identifier)

        resolved_parent_task_id: Optional[uuid.UUID] = None
        if parent_task_identifier:
            resolved_parent_task_id = _resolve_task_id(conn, parent_task_identifier)
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
            id=task_id, title=title, status=status,
            project_id=resolved_project_id, parent_task_id=resolved_parent_task_id,
            created_at=current_time, modified_at=current_time,
            priority=priority, due_date=parsed_due_date, details_md_path=md_path
        )
        
        added_task = db.add_task(conn, task)
        return added_task
    finally:
        if conn:
            conn.close()

def find_task(task_identifier: Union[str, uuid.UUID], base_data_dir: Optional[Path] = None) -> Optional[Task]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        try:
            resolved_id = _resolve_task_id(conn, task_identifier) # This now raises if not found
            return db.get_task_by_id(conn, resolved_id) # So this should always find it
        except ValueError: 
            return None
    finally:
        if conn:
            conn.close()

def list_all_tasks(
    project_identifier: Optional[Union[str, uuid.UUID]] = None,
    status: Optional[TaskStatus] = None,
    parent_task_identifier: Optional[Union[str, uuid.UUID]] = None,
    include_subtasks_of_any_parent: bool = False,
    base_data_dir: Optional[Path] = None
) -> List[Task]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_project_id: Optional[uuid.UUID] = None
        if project_identifier:
            resolved_project_id = _resolve_project_id(conn, project_identifier)

        resolved_parent_task_id: Optional[uuid.UUID] = None
        if parent_task_identifier:
            resolved_parent_task_id = _resolve_task_id(conn, parent_task_identifier)
            
        return db.list_tasks(
            conn, project_id=resolved_project_id, status=status,
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
    new_due_date_iso: Optional[str] = None, 
    new_details: Optional[str] = None,    
    new_project_identifier: Optional[Union[str, uuid.UUID]] = None,
    clear_project: bool = False,
    base_data_dir: Optional[Path] = None
) -> Optional[Task]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        # find_task now uses its own connection, so we need to resolve ID with current connection
        # or fetch the task object with the current connection to modify it.
        resolved_task_id = _resolve_task_id(conn, task_identifier) # Ensures task exists
        task = db.get_task_by_id(conn, resolved_task_id) # Fetch with current connection
        if not task: # Should not happen if _resolve_task_id worked
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
            elif new_status != TaskStatus.DONE: # Also handles if it was DONE and now isn't
                task.completed_at = None 

        if new_priority is not None and task.priority != new_priority:
            task.priority = new_priority
            updated = True

        if new_due_date_iso is not None:
            if new_due_date_iso == "": 
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
            if task.details_md_path is None and new_details: 
                task.details_md_path = utils.generate_markdown_file_path(task.id, "task", base_data_dir)
            if task.details_md_path: 
                 utils.write_markdown_file(task.details_md_path, new_details)
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
            return db.update_task(conn, task)
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
    return update_task_details_and_status(
        task_identifier=task_identifier,
        new_status=new_status,
        base_data_dir=base_data_dir
    )

def get_task_file_path(
    task_identifier: Union[str, uuid.UUID],
    file_type: str = "details",
    base_data_dir: Optional[Path] = None,
    create_if_missing_in_object: bool = True
) -> Optional[Path]:
    if file_type != "details":
        pass # Or raise error

    # find_task opens its own connection. To use the _resolve_task_id with a shared connection,
    # or to ensure consistency, we might need to adjust.
    # For now, let find_task do its work.
    task = find_task(task_identifier, base_data_dir=base_data_dir)
    if not task:
        # find_task already returns None if not found by _resolve_task_id
        # _resolve_task_id would have raised ValueError if format was bad or ID not found.
        # This means find_task should have caught that and returned None.
        # So, if task is None here, it means it wasn't found.
        raise ValueError(f"Task with identifier '{task_identifier}' not found for getpath.")


    if task.details_md_path:
        return task.details_md_path
    elif create_if_missing_in_object:
        return utils.generate_markdown_file_path(task.id, "task", base_data_dir)
    
    return None


def delete_task_permanently(
    task_identifier: Union[str, uuid.UUID],
    base_data_dir: Optional[Path] = None
) -> bool:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_task_id = _resolve_task_id(conn, task_identifier)
        task_obj = db.get_task_by_id(conn, resolved_task_id)
        if not task_obj:
            return False # Should not happen if _resolve_task_id worked

        if task_obj.details_md_path and task_obj.details_md_path.exists():
            try:
                task_obj.details_md_path.unlink()
            except OSError:
                pass 
        
        return db.delete_task(conn, task_obj.id)
    except ValueError: 
        return False
    finally:
        if conn:
            conn.close()

# End of File: knowledge_manager/task_ops.py
