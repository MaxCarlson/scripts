# File: knowledge_manager/task_ops.py
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Union
from datetime import date, datetime, timezone 

from . import db
from . import utils
from .models import Task, TaskStatus, Project 
# from textual import log # Uncomment if using log here

def _resolve_project_id(conn: db.sqlite3.Connection, project_identifier: Optional[Union[str, uuid.UUID]]) -> Optional[uuid.UUID]:
    if not project_identifier: return None
    if isinstance(project_identifier, uuid.UUID):
        project_obj = db.get_project_by_id(conn, project_identifier)
        if project_obj: return project_identifier
        else: raise ValueError(f"Project with ID '{project_identifier}' not found.")
    project_obj = db.get_project_by_name(conn, str(project_identifier))
    if project_obj: return project_obj.id
    else:
        try:
            project_id_uuid = uuid.UUID(str(project_identifier))
            project_obj_by_uuid = db.get_project_by_id(conn, project_id_uuid)
            if project_obj_by_uuid: return project_id_uuid
        except ValueError: pass 
        raise ValueError(f"Project with identifier '{project_identifier}' not found.")

def _resolve_task_id(
    conn: db.sqlite3.Connection, 
    task_identifier: Union[str, uuid.UUID],
    project_identifier: Optional[Union[str, uuid.UUID]] = None
) -> uuid.UUID:
    if not task_identifier: raise ValueError("Task identifier cannot be empty.")
    if isinstance(task_identifier, uuid.UUID):
        task_obj = db.get_task_by_id(conn, task_identifier)
        if task_obj: return task_identifier
        else: raise ValueError(f"Task with ID '{task_identifier}' not found.")
    try:
        task_id_uuid = uuid.UUID(str(task_identifier))
        task_obj_by_uuid = db.get_task_by_id(conn, task_id_uuid)
        if task_obj_by_uuid: return task_id_uuid
    except ValueError: pass
    title_prefix_to_search = str(task_identifier)
    resolved_project_id_for_search: Optional[uuid.UUID] = None
    if project_identifier:
        try: resolved_project_id_for_search = _resolve_project_id(conn, project_identifier)
        except ValueError: pass 
    tasks_found = db.get_tasks_by_title_prefix(conn, title_prefix_to_search, project_id=resolved_project_id_for_search)
    if not tasks_found:
        scope_msg = f" in project context '{project_identifier}'" if resolved_project_id_for_search and project_identifier else ""
        raise ValueError(f"No task found with ID or title prefix '{title_prefix_to_search}'{scope_msg}.")
    if len(tasks_found) == 1: return tasks_found[0].id
    else:
        task_options = "\n".join([f"  - '{t.title}' (ID: {t.id})" for t in tasks_found])
        scope_msg = f" in project context '{project_identifier}'" if resolved_project_id_for_search and project_identifier else ""
        raise ValueError(
            f"Multiple tasks found with title prefix '{title_prefix_to_search}'{scope_msg}. "
            f"Please be more specific or use a UUID:\n{task_options}"
        )

def create_new_task(
    title: str, project_identifier: Optional[Union[str, uuid.UUID]] = None,
    parent_task_identifier: Optional[Union[str, uuid.UUID]] = None,
    status: TaskStatus = TaskStatus.TODO, priority: int = 3,
    due_date_iso: Optional[str] = None, details: Optional[str] = None,
    base_data_dir: Optional[Path] = None
) -> Task:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_project_id: Optional[uuid.UUID] = None
        if project_identifier: resolved_project_id = _resolve_project_id(conn, project_identifier)
        resolved_parent_task_id: Optional[uuid.UUID] = None
        if parent_task_identifier:
            resolved_parent_task_id = _resolve_task_id(conn, parent_task_identifier, project_identifier=resolved_project_id)
            if resolved_parent_task_id and resolved_project_id:
                parent_task_obj = db.get_task_by_id(conn, resolved_parent_task_id)
                if parent_task_obj and parent_task_obj.project_id != resolved_project_id:
                    raise ValueError("Parent task does not belong to the specified project for the new task.")
        task_id = uuid.uuid4(); current_time = utils.get_current_utc_timestamp()
        md_path: Optional[Path] = None
        if details is not None: # If details string is provided (even empty), create file and path
            md_path = utils.generate_markdown_file_path(task_id, "task", base_data_dir)
            utils.write_markdown_file(md_path, details)
        parsed_due_date: Optional[date] = None
        if due_date_iso:
            try: parsed_due_date = date.fromisoformat(due_date_iso)
            except ValueError: raise ValueError(f"Invalid due_date format: '{due_date_iso}'. Expected YYYY-MM-DD.")
        task = Task(
            id=task_id, title=title, status=status, project_id=resolved_project_id, 
            parent_task_id=resolved_parent_task_id, created_at=current_time, modified_at=current_time,
            priority=priority, due_date=parsed_due_date, details_md_path=md_path
        )
        return db.add_task(conn, task)
    finally:
        if conn: conn.close()

def find_task(
    task_identifier: Union[str, uuid.UUID], 
    project_identifier: Optional[Union[str, uuid.UUID]] = None, 
    base_data_dir: Optional[Path] = None
) -> Optional[Task]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_id = _resolve_task_id(conn, task_identifier, project_identifier=project_identifier)
        return db.get_task_by_id(conn, resolved_id) 
    except ValueError: return None 
    finally:
        if conn: conn.close()

def list_all_tasks(
    project_identifier: Optional[Union[str, uuid.UUID]] = None, status: Optional[TaskStatus] = None,
    parent_task_identifier: Optional[Union[str, uuid.UUID]] = None,
    include_subtasks_of_any_parent: bool = False, base_data_dir: Optional[Path] = None
) -> List[Task]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_project_id: Optional[uuid.UUID] = None
        if project_identifier: resolved_project_id = _resolve_project_id(conn, project_identifier)
        resolved_parent_task_id: Optional[uuid.UUID] = None
        if parent_task_identifier:
            resolved_parent_task_id = _resolve_task_id(conn, parent_task_identifier, project_identifier=resolved_project_id)
        return db.list_tasks(
            conn, project_id=resolved_project_id, status=status,
            parent_task_id=resolved_parent_task_id,
            include_subtasks_of_any_parent=include_subtasks_of_any_parent
        )
    finally:
        if conn: conn.close()

def update_task_details_and_status(
    task_identifier: Union[str, uuid.UUID],
    new_title: Optional[str] = None, new_status: Optional[TaskStatus] = None,
    new_priority: Optional[int] = None, new_due_date_iso: Optional[str] = None, 
    new_details: Optional[str] = None,    
    new_project_identifier: Optional[Union[str, uuid.UUID]] = None,
    clear_project: bool = False,
    current_project_context_for_search: Optional[Union[str, uuid.UUID]] = None,
    base_data_dir: Optional[Path] = None
) -> Optional[Task]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_task_id = _resolve_task_id(conn, task_identifier, project_identifier=current_project_context_for_search)
        task = db.get_task_by_id(conn, resolved_task_id)
        if not task: return None 

        updated = False
        if new_title is not None and task.title != new_title:
            task.title = new_title; updated = True
        if new_status is not None and task.status != new_status:
            task.status = new_status; updated = True
            if new_status == TaskStatus.DONE and task.completed_at is None:
                task.completed_at = utils.get_current_utc_timestamp()
            elif new_status != TaskStatus.DONE: task.completed_at = None 
        if new_priority is not None and task.priority != new_priority:
            task.priority = new_priority; updated = True
        if new_due_date_iso is not None:
            if new_due_date_iso == "": 
                if task.due_date is not None: task.due_date = None; updated = True
            else:
                try: parsed_due_date = date.fromisoformat(new_due_date_iso)
                except ValueError: raise ValueError(f"Invalid new_due_date format: '{new_due_date_iso}'. Expected YYYY-MM-DD.")
                if task.due_date != parsed_due_date: task.due_date = parsed_due_date; updated = True
        
        # Refined logic for details and details_md_path
        if new_details is not None: # User explicitly wants to interact with details
            if task.details_md_path is None: # If no path exists yet, generate it
                task.details_md_path = utils.generate_markdown_file_path(task.id, "task", base_data_dir)
            # Now task.details_md_path is guaranteed to be set
            utils.write_markdown_file(task.details_md_path, new_details) # Write content (even if empty string)
            updated = True # Mark as updated to ensure DB save of path and modified_at

        if clear_project:
            if task.project_id is not None: task.project_id = None; updated = True
        elif new_project_identifier is not None:
            resolved_new_project_id = _resolve_project_id(conn, new_project_identifier)
            if task.project_id != resolved_new_project_id:
                task.project_id = resolved_new_project_id; updated = True
        
        if updated: return db.update_task(conn, task)
        else: return task
    except ValueError as e: raise e 
    finally:
        if conn: conn.close()

def mark_task_status(
    task_identifier: Union[str, uuid.UUID], new_status: TaskStatus,
    project_identifier_context: Optional[Union[str, uuid.UUID]] = None, 
    base_data_dir: Optional[Path] = None
) -> Optional[Task]:
    return update_task_details_and_status(
        task_identifier=task_identifier, new_status=new_status,
        current_project_context_for_search=project_identifier_context,
        base_data_dir=base_data_dir
    )

def get_task_file_path(
    task_identifier: Union[str, uuid.UUID], file_type: str = "details",
    project_identifier_context: Optional[Union[str, uuid.UUID]] = None, 
    base_data_dir: Optional[Path] = None, create_if_missing_in_object: bool = True
) -> Optional[Path]:
    if file_type != "details": pass 
    task = find_task(task_identifier, project_identifier=project_identifier_context, base_data_dir=base_data_dir)
    if not task:
        # Re-call _resolve_task_id to get its specific error message if find_task returned None
        conn = db.get_db_connection(utils.get_db_path(base_data_dir))
        try: _resolve_task_id(conn, task_identifier, project_identifier=project_identifier_context)
        except ValueError as e: raise ValueError(f"For getpath: {e}") 
        finally:
            if conn: conn.close()
        raise ValueError(f"Task with identifier '{task_identifier}' not found for getpath (unexpected).")

    if task.details_md_path: return task.details_md_path
    elif create_if_missing_in_object:
        return utils.generate_markdown_file_path(task.id, "task", base_data_dir)
    return None

def delete_task_permanently(
    task_identifier: Union[str, uuid.UUID],
    project_identifier_context: Optional[Union[str, uuid.UUID]] = None, 
    base_data_dir: Optional[Path] = None
) -> bool:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        resolved_task_id = _resolve_task_id(conn, task_identifier, project_identifier=project_identifier_context)
        task_obj = db.get_task_by_id(conn, resolved_task_id)
        if not task_obj: return False 
        if task_obj.details_md_path and task_obj.details_md_path.exists():
            try: task_obj.details_md_path.unlink()
            except OSError: pass 
        return db.delete_task(conn, task_obj.id)
    except ValueError: return False
    finally:
        if conn: conn.close()
