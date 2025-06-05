# File: knowledge_manager/utils.py
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
# from textual import log # Uncomment if you want to use log here

# --- Configuration ---
DEFAULT_BASE_DATA_DIR_NAME = "knowledge_manager_data"
PROJECT_FILES_DIR_NAME = "projects"
TASK_FILES_DIR_NAME = "tasks"
DB_FILE_NAME = "knowledge_manager.db"

# --- Path Management ---
def get_base_data_dir(user_specified_path: Optional[Path] = None) -> Path:
    if user_specified_path: base_dir = user_specified_path
    else: base_dir = Path.home() / ".local" / "share" / DEFAULT_BASE_DATA_DIR_NAME
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

def get_db_path(base_data_dir: Optional[Path] = None) -> Path:
    resolved_base_dir = get_base_data_dir(base_data_dir)
    return resolved_base_dir / DB_FILE_NAME

def get_content_files_base_dir(base_data_dir: Optional[Path] = None) -> Path:
    resolved_base_dir = get_base_data_dir(base_data_dir)
    content_dir = resolved_base_dir / "files"
    content_dir.mkdir(parents=True, exist_ok=True)
    return content_dir

def get_project_content_dir(base_data_dir: Optional[Path] = None) -> Path:
    content_base = get_content_files_base_dir(base_data_dir)
    project_files_dir = content_base / PROJECT_FILES_DIR_NAME
    project_files_dir.mkdir(parents=True, exist_ok=True)
    return project_files_dir

def get_task_content_dir(base_data_dir: Optional[Path] = None) -> Path:
    content_base = get_content_files_base_dir(base_data_dir)
    task_files_dir = content_base / TASK_FILES_DIR_NAME
    task_files_dir.mkdir(parents=True, exist_ok=True)
    return task_files_dir

def generate_markdown_file_path(entity_id: uuid.UUID, entity_type: str, base_data_dir: Optional[Path] = None) -> Path:
    if entity_type == "project": parent_dir = get_project_content_dir(base_data_dir)
    elif entity_type == "task": parent_dir = get_task_content_dir(base_data_dir)
    else: raise ValueError(f"Unknown entity_type for Markdown file: {entity_type}")
    return parent_dir / f"{str(entity_id)}.md"

# --- File Operations ---
def write_markdown_file(file_path: Path, content: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f: f.write(content)

def read_markdown_file(file_path: Path) -> Optional[str]:
    if not file_path.exists() or not file_path.is_file(): 
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f: return f.read()
    except IOError: 
        # log.warning(f"IOError reading markdown file {file_path}") # If using logging
        return None
    except Exception as e: 
        # log.error(f"Unexpected error reading markdown file {file_path}: {e}", exc_info=True) # If using logging
        return None

# --- Timestamp Utilities ---
def get_current_utc_timestamp() -> datetime:
    return datetime.now(timezone.utc)
