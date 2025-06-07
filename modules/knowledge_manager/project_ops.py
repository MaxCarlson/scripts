# File: knowledge_manager/project_ops.py
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Union
import sqlite3 # For type hinting and potential error catching

from . import db # Relative import for db module in the same package
from .models import Project, ProjectStatus
# Use relative import for utils if it's consistently in the same package
from . import utils 

def create_new_project(
    name: str,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    description: Optional[str] = None,
    base_data_dir: Optional[Path] = None
) -> Project:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    
    try:
        existing_by_name = db.get_project_by_name(conn, name)
        if existing_by_name:
            raise ValueError(f"A project with the name '{name}' already exists.")

        project_id = uuid.uuid4()
        current_time = utils.get_current_utc_timestamp()
        
        md_path: Optional[Path] = None
        if description is not None:
            md_path = utils.generate_markdown_file_path(project_id, "project", base_data_dir)
            utils.write_markdown_file(md_path, description)

        project = Project(
            id=project_id,
            name=name,
            status=status,
            created_at=current_time,
            modified_at=current_time, # Set on creation
            description_md_path=md_path
        )
        
        added_project = db.add_project(conn, project) # db.add_project also sets modified_at
        return added_project
    finally:
        if conn: 
            conn.close()

def find_project(identifier: Union[str, uuid.UUID], base_data_dir: Optional[Path] = None) -> Optional[Project]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        project: Optional[Project] = None
        # If it's a UUID object, just use it.
        if isinstance(identifier, uuid.UUID):
            return db.get_project_by_id(conn, identifier)

        # If it's a string, try to parse as UUID first.
        try:
            project_id = uuid.UUID(identifier)
            project = db.get_project_by_id(conn, project_id)
        except (ValueError, TypeError):
            # Not a valid UUID string, so it must be a name.
            project = None
        
        # If found by UUID string, return. Otherwise, search by name.
        if project:
            return project
        else:
            return db.get_project_by_name(conn, str(identifier))
    finally:
        if conn:
            conn.close()

def list_all_projects(
    status: Optional[ProjectStatus] = None,
    base_data_dir: Optional[Path] = None
) -> List[Project]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        return db.list_projects(conn, status=status)
    finally:
        if conn:
            conn.close()

def update_project_details(
    project_identifier: Union[str, uuid.UUID],
    new_name: Optional[str] = None,
    new_status: Optional[ProjectStatus] = None,
    new_description: Optional[str] = None,
    base_data_dir: Optional[Path] = None
) -> Optional[Project]:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        project = find_project(project_identifier, base_data_dir=base_data_dir) 
        if not project:
            return None

        updated = False
        if new_name is not None and project.name != new_name:
            existing_by_new_name = db.get_project_by_name(conn, new_name)
            if existing_by_new_name and existing_by_new_name.id != project.id:
                raise ValueError(f"A project with the name '{new_name}' already exists.")
            project.name = new_name
            updated = True
        
        if new_status is not None and project.status != new_status:
            project.status = new_status
            updated = True

        if new_description is not None:
            if project.description_md_path is None:
                project.description_md_path = utils.generate_markdown_file_path(project.id, "project", base_data_dir)
            utils.write_markdown_file(project.description_md_path, new_description)
            updated = True 
        
        if updated:
            return db.update_project(conn, project) 
        else:
            return project # No changes made, return original found project
    finally:
        if conn:
            conn.close()

def get_project_with_details(
    project_identifier: str,
    base_data_dir: Optional[Path] = None
) -> Optional[Tuple[Project, Optional[str]]]:
    project = find_project(project_identifier, base_data_dir=base_data_dir)
    if not project:
        return None
    
    description_content: Optional[str] = None
    if project.description_md_path:
        description_content = utils.read_markdown_file(project.description_md_path)
    return project, description_content

def delete_project_permanently(
    project_identifier: str,
    base_data_dir: Optional[Path] = None
) -> bool:
    db_p = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_p)
    try:
        project = find_project(project_identifier, base_data_dir=base_data_dir) 
        if not project:
            return False

        if project.description_md_path and project.description_md_path.exists():
            try:
                project.description_md_path.unlink()
            except OSError:
                pass 
        return db.delete_project(conn, project.id)
    finally:
        if conn:
            conn.close()
