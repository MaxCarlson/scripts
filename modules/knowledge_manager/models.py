# File: knowledge_manager/models.py
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from enum import Enum
from pathlib import Path
from typing import Optional

class ProjectStatus(Enum):
    ACTIVE = "active"
    BACKLOG = "backlog"
    COMPLETED = "completed"

class TaskStatus(Enum):
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"

@dataclass
class Project:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    description_md_path: Optional[Path] = None

    def __post_init__(self):
        if isinstance(self.status, str):
            self.status = ProjectStatus(self.status)
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)
        if isinstance(self.modified_at, str):
            self.modified_at = datetime.fromisoformat(self.modified_at)
        if isinstance(self.description_md_path, str):
            self.description_md_path = Path(self.description_md_path) if self.description_md_path else None

@dataclass
class Task:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = ""
    status: TaskStatus = TaskStatus.TODO
    project_id: Optional[uuid.UUID] = None
    parent_task_id: Optional[uuid.UUID] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    priority: int = 3  # Assuming 1-5, with 3 as a neutral default
    due_date: Optional[date] = None
    details_md_path: Optional[Path] = None

    def __post_init__(self):
        if isinstance(self.status, str):
            self.status = TaskStatus(self.status)
        if isinstance(self.project_id, str):
            self.project_id = uuid.UUID(self.project_id) if self.project_id else None
        if isinstance(self.parent_task_id, str):
            self.parent_task_id = uuid.UUID(self.parent_task_id) if self.parent_task_id else None
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)
        if isinstance(self.modified_at, str):
            self.modified_at = datetime.fromisoformat(self.modified_at)
        if isinstance(self.completed_at, str):
            self.completed_at = datetime.fromisoformat(self.completed_at) if self.completed_at else None
        if isinstance(self.due_date, str):
            self.due_date = date.fromisoformat(self.due_date) if self.due_date else None
        if isinstance(self.details_md_path, str):
            self.details_md_path = Path(self.details_md_path) if self.details_md_path else None

@dataclass
class Tag:
    """Tag for categorizing projects and tasks"""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    color: Optional[str] = None  # Hex color code (e.g., "#FF5733")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)

@dataclass
class Note:
    """Rich text note attached to a project or task"""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    content: str = ""
    project_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if isinstance(self.project_id, str):
            self.project_id = uuid.UUID(self.project_id) if self.project_id else None
        if isinstance(self.task_id, str):
            self.task_id = uuid.UUID(self.task_id) if self.task_id else None
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)
        if isinstance(self.modified_at, str):
            self.modified_at = datetime.fromisoformat(self.modified_at)

@dataclass
class Attachment:
    """File attachment for a project or task"""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    file_path: Path = field(default_factory=Path)
    filename: str = ""
    mime_type: Optional[str] = None
    project_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)
        if isinstance(self.project_id, str):
            self.project_id = uuid.UUID(self.project_id) if self.project_id else None
        if isinstance(self.task_id, str):
            self.task_id = uuid.UUID(self.task_id) if self.task_id else None
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)

@dataclass
class Lock:
    """Lock file for preventing concurrent edits during sync"""
    entity_id: uuid.UUID  # Project or Task ID
    entity_type: str  # "project" or "task"
    locked_by: str  # System identifier (hostname + username)
    locked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if isinstance(self.entity_id, str):
            self.entity_id = uuid.UUID(self.entity_id)
        if isinstance(self.locked_at, str):
            self.locked_at = datetime.fromisoformat(self.locked_at)

# End of File: knowledge_manager/models.py
