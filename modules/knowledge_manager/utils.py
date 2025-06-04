# File: knowledge_manager/utils.py
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# --- Configuration ---
# These could eventually be loaded from a config file
DEFAULT_BASE_DATA_DIR_NAME = "knowledge_manager_data"
PROJECT_FILES_DIR_NAME = "projects"
TASK_FILES_DIR_NAME = "tasks"
DB_FILE_NAME = "knowledge_manager.db" # Consistent with db.py

# --- Path Management ---

def get_base_data_dir(user_specified_path: Optional[Path] = None) -> Path:
    """
    Determines the base directory for all knowledge_manager data.
    Uses user_specified_path if provided, otherwise defaults to
    ~/.local/share/knowledge_manager_data/
    Creates the directory if it doesn't exist.
    """
    if user_specified_path:
        base_dir = user_specified_path
    else:
        base_dir = Path.home() / ".local" / "share" / DEFAULT_BASE_DATA_DIR_NAME
    
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

def get_db_path(base_data_dir: Optional[Path] = None) -> Path:
    """
    Gets the full path to the SQLite database file.
    This should align with db.get_default_db_path if no base_data_dir is given
    to project_ops/task_ops, but provides flexibility.
    """
    resolved_base_dir = get_base_data_dir(base_data_dir)
    return resolved_base_dir / DB_FILE_NAME


def get_content_files_base_dir(base_data_dir: Optional[Path] = None) -> Path:
    """
    Gets the base directory for storing Markdown content files.
    e.g., <base_data_dir>/files/
    """
    resolved_base_dir = get_base_data_dir(base_data_dir)
    content_dir = resolved_base_dir / "files"
    content_dir.mkdir(parents=True, exist_ok=True)
    return content_dir

def get_project_content_dir(base_data_dir: Optional[Path] = None) -> Path:
    """
    Gets the directory for storing project-specific Markdown files.
    e.g., <base_data_dir>/files/projects/
    """
    content_base = get_content_files_base_dir(base_data_dir)
    project_files_dir = content_base / PROJECT_FILES_DIR_NAME
    project_files_dir.mkdir(parents=True, exist_ok=True)
    return project_files_dir

def get_task_content_dir(base_data_dir: Optional[Path] = None) -> Path:
    """
    Gets the directory for storing task-specific Markdown files.
    e.g., <base_data_dir>/files/tasks/
    """
    content_base = get_content_files_base_dir(base_data_dir)
    task_files_dir = content_base / TASK_FILES_DIR_NAME
    task_files_dir.mkdir(parents=True, exist_ok=True)
    return task_files_dir

def generate_markdown_file_path(entity_id: uuid.UUID, entity_type: str, base_data_dir: Optional[Path] = None) -> Path:
    """
    Generates a standardized path for a Markdown content file.
    entity_type should be 'project' or 'task'.
    """
    if entity_type == "project":
        parent_dir = get_project_content_dir(base_data_dir)
    elif entity_type == "task":
        parent_dir = get_task_content_dir(base_data_dir)
    else:
        raise ValueError(f"Unknown entity_type for Markdown file: {entity_type}")
    
    return parent_dir / f"{str(entity_id)}.md"

# --- File Operations ---

def write_markdown_file(file_path: Path, content: str) -> None:
    """Writes content to a Markdown file, creating parent directories if necessary."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

def read_markdown_file(file_path: Path) -> Optional[str]:
    """Reads content from a Markdown file. Returns None if file not found."""
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except IOError: # Or FileNotFoundError in Python 3.3+
        return None

# --- Timestamp Utilities ---
def get_current_utc_timestamp() -> datetime:
    """Returns the current datetime in UTC."""
    return datetime.now(timezone.utc)

# End of File: knowledge_manager/utils.py
