from .duplicate_finder import find_duplicates, delete_files, summarize_statistics
from .file_organizer import organize_files
from .file_utils import merge_files
from .utils import calculate_file_hash, write_debug
from .replacer import (
    Match,
    ReplacementResult,
    Statistics,
    find_matches_with_ripgrep,
    apply_replacements,
    run_replacer,
)
from .replacer_state import FileContent, FileState
from .replacer_operations import Operation, OperationManager

__all__ = [
    "find_duplicates",
    "delete_files",
    "summarize_statistics",
    "organize_files",
    "merge_files",
    "calculate_file_hash",
    "write_debug",
    "Match",
    "ReplacementResult",
    "Statistics",
    "find_matches_with_ripgrep",
    "apply_replacements",
    "run_replacer",
    "FileContent",
    "FileState",
    "Operation",
    "OperationManager",
]
