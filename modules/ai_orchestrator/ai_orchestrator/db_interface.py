"""Database interface for accessing knowledge_manager data."""

import sys
import sqlite3
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, date

# Import knowledge_manager if available
try:
    from knowledge_manager import models as km_models
    from knowledge_manager import db as km_db
    KM_AVAILABLE = True
except ImportError:
    KM_AVAILABLE = False
    km_models = None
    km_db = None


class KnowledgeDB:
    """Human-friendly interface to the knowledge_manager SQLite database."""

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database. If None, uses default location.
        """
        if not KM_AVAILABLE:
            raise ImportError(
                "knowledge_manager module not available. "
                "Please install it first: cd modules/knowledge_manager && pip install -e ."
            )

        if db_path is None:
            db_path = km_db.get_default_db_path()

        self.db_path = Path(db_path)

        # Initialize database if it doesn't exist
        if not self.db_path.exists():
            km_db.init_db(self.db_path)

        self.conn = km_db.get_db_connection(self.db_path)

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    # --- Project Methods ---

    def list_projects(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all projects as dictionaries.

        Args:
            status: Filter by status ('active', 'backlog', 'completed')

        Returns:
            List of project dictionaries
        """
        status_enum = None
        if status:
            status_enum = km_models.ProjectStatus(status)

        projects = km_db.list_projects(self.conn, status=status_enum)
        return [self._project_to_dict(p) for p in projects]

    def get_project(self, project_id: Optional[str] = None, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a single project by ID or name.

        Args:
            project_id: Project UUID string
            name: Project name

        Returns:
            Project dictionary or None
        """
        if project_id:
            project = km_db.get_project_by_id(self.conn, uuid.UUID(project_id))
        elif name:
            project = km_db.get_project_by_name(self.conn, name)
        else:
            return None

        return self._project_to_dict(project) if project else None

    def create_project(self, name: str, status: str = "active", description_md_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new project.

        Args:
            name: Project name
            status: Project status ('active', 'backlog', 'completed')
            description_md_path: Optional path to markdown description

        Returns:
            Created project dictionary
        """
        project = km_models.Project(
            name=name,
            status=km_models.ProjectStatus(status),
            description_md_path=Path(description_md_path) if description_md_path else None
        )
        created = km_db.add_project(self.conn, project)
        return self._project_to_dict(created)

    def update_project(self, project_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Update a project.

        Args:
            project_id: Project UUID string
            **kwargs: Fields to update (name, status, description_md_path)

        Returns:
            Updated project dictionary or None
        """
        project = km_db.get_project_by_id(self.conn, uuid.UUID(project_id))
        if not project:
            return None

        if "name" in kwargs:
            project.name = kwargs["name"]
        if "status" in kwargs:
            project.status = km_models.ProjectStatus(kwargs["status"])
        if "description_md_path" in kwargs:
            project.description_md_path = Path(kwargs["description_md_path"]) if kwargs["description_md_path"] else None

        updated = km_db.update_project(self.conn, project)
        return self._project_to_dict(updated) if updated else None

    def delete_project(self, project_id: str) -> bool:
        """
        Delete a project.

        Args:
            project_id: Project UUID string

        Returns:
            True if deleted, False otherwise
        """
        return km_db.delete_project(self.conn, uuid.UUID(project_id))

    # --- Task Methods ---

    def list_tasks(
        self,
        project_id: Optional[str] = None,
        status: Optional[List[str]] = None,
        parent_task_id: Optional[str] = None,
        include_subtasks: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List tasks with optional filters.

        Args:
            project_id: Filter by project UUID
            status: Filter by status list ('todo', 'in-progress', 'done')
            parent_task_id: Filter by parent task UUID (None = top-level only)
            include_subtasks: Include subtasks of any parent

        Returns:
            List of task dictionaries
        """
        proj_uuid = uuid.UUID(project_id) if project_id else None
        status_enums = [km_models.TaskStatus(s) for s in status] if status else None
        parent_uuid = uuid.UUID(parent_task_id) if parent_task_id else None

        tasks = km_db.list_tasks(
            self.conn,
            project_id=proj_uuid,
            status_filter=status_enums,
            parent_task_id=parent_uuid,
            include_subtasks_of_any_parent=include_subtasks
        )
        return [self._task_to_dict(t) for t in tasks]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single task by ID.

        Args:
            task_id: Task UUID string

        Returns:
            Task dictionary or None
        """
        task = km_db.get_task_by_id(self.conn, uuid.UUID(task_id))
        return self._task_to_dict(task) if task else None

    def create_task(
        self,
        title: str,
        project_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        status: str = "todo",
        priority: int = 3,
        due_date: Optional[str] = None,
        details_md_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new task.

        Args:
            title: Task title
            project_id: Optional project UUID
            parent_task_id: Optional parent task UUID (for subtasks)
            status: Task status ('todo', 'in-progress', 'done')
            priority: Priority 1-5 (3 is default)
            due_date: Optional due date (ISO format)
            details_md_path: Optional path to markdown details

        Returns:
            Created task dictionary
        """
        task = km_models.Task(
            title=title,
            project_id=uuid.UUID(project_id) if project_id else None,
            parent_task_id=uuid.UUID(parent_task_id) if parent_task_id else None,
            status=km_models.TaskStatus(status),
            priority=priority,
            due_date=date.fromisoformat(due_date) if due_date else None,
            details_md_path=Path(details_md_path) if details_md_path else None
        )
        created = km_db.add_task(self.conn, task)
        return self._task_to_dict(created)

    def update_task(self, task_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Update a task.

        Args:
            task_id: Task UUID string
            **kwargs: Fields to update

        Returns:
            Updated task dictionary or None
        """
        task = km_db.get_task_by_id(self.conn, uuid.UUID(task_id))
        if not task:
            return None

        if "title" in kwargs:
            task.title = kwargs["title"]
        if "status" in kwargs:
            task.status = km_models.TaskStatus(kwargs["status"])
        if "priority" in kwargs:
            task.priority = kwargs["priority"]
        if "due_date" in kwargs:
            task.due_date = date.fromisoformat(kwargs["due_date"]) if kwargs["due_date"] else None
        if "details_md_path" in kwargs:
            task.details_md_path = Path(kwargs["details_md_path"]) if kwargs["details_md_path"] else None

        updated = km_db.update_task(self.conn, task)
        return self._task_to_dict(updated) if updated else None

    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.

        Args:
            task_id: Task UUID string

        Returns:
            True if deleted, False otherwise
        """
        return km_db.delete_task(self.conn, uuid.UUID(task_id))

    # --- Helper Methods ---

    @staticmethod
    def _project_to_dict(project) -> Dict[str, Any]:
        """Convert Project model to dictionary."""
        if not project:
            return {}
        return {
            "id": str(project.id),
            "name": project.name,
            "status": project.status.value,
            "created_at": project.created_at.isoformat(),
            "modified_at": project.modified_at.isoformat(),
            "description_md_path": str(project.description_md_path) if project.description_md_path else None
        }

    @staticmethod
    def _task_to_dict(task) -> Dict[str, Any]:
        """Convert Task model to dictionary."""
        if not task:
            return {}
        return {
            "id": str(task.id),
            "title": task.title,
            "status": task.status.value,
            "project_id": str(task.project_id) if task.project_id else None,
            "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
            "created_at": task.created_at.isoformat(),
            "modified_at": task.modified_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "priority": task.priority,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "details_md_path": str(task.details_md_path) if task.details_md_path else None
        }

    # --- View Helpers ---

    def get_project_tree(self, project_id: str) -> Dict[str, Any]:
        """
        Get a complete project with all tasks and subtasks in a tree structure.

        Args:
            project_id: Project UUID string

        Returns:
            Dictionary with project and nested tasks
        """
        project = self.get_project(project_id=project_id)
        if not project:
            return {}

        # Get all tasks for this project
        all_tasks = self.list_tasks(project_id=project_id, include_subtasks=True)

        # Build task tree
        tasks_by_id = {t["id"]: t for t in all_tasks}
        root_tasks = []

        for task in all_tasks:
            # Add children list to each task
            task["subtasks"] = []

            if not task["parent_task_id"]:
                root_tasks.append(task)
            else:
                parent = tasks_by_id.get(task["parent_task_id"])
                if parent:
                    parent["subtasks"].append(task)

        project["tasks"] = root_tasks
        return project
