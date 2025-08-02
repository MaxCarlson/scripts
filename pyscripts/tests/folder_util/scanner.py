# folder_util/scanner.py

import os
import re
import stat
import datetime
from pathlib import Path
from typing import List, Dict, Any

from .utils.debug_utils import write_debug

def get_file_metadata(path: Path, include_size: bool, include_date: bool, extra: Dict[str, bool]) -> Dict[str, Any]:
    metadata = {}
    try:
        stat_result = path.stat()
    except Exception as e:
        write_debug(f"Error reading stat for {path}: {e}", channel="Warning")
        return metadata

    metadata['name'] = path.name
    metadata['full_path'] = str(path.resolve())
    if include_size and path.is_file():
        metadata['size'] = stat_result.st_size
    elif include_size and path.is_dir():
        metadata['size'] = calculate_folder_size(path)
    else:
        metadata['size'] = 0

    if include_date:
        # On Windows, st_ctime is the creation time; on Unix, try st_birthtime if available
        if os.name == 'nt':
            metadata['date_created'] = datetime.datetime.fromtimestamp(stat_result.st_ctime)
        else:
            metadata['date_created'] = datetime.datetime.fromtimestamp(getattr(stat_result, 'st_birthtime', stat_result.st_ctime))
        metadata['date_modified'] = datetime.datetime.fromtimestamp(stat_result.st_mtime)
        metadata['date_accessed'] = datetime.datetime.fromtimestamp(stat_result.st_atime)

    if extra.get("permissions", False):
        metadata['permissions'] = stat.filemode(stat_result.st_mode)
    if extra.get("owner", False):
        try:
            import pwd
            metadata['owner'] = pwd.getpwuid(stat_result.st_uid).pw_name
        except Exception:
            metadata['owner'] = "N/A"
    # Additional metadata (e.g., git info, file_count) can be added later.
    return metadata

def calculate_folder_size(folder: Path) -> int:
    total_size = 0
    try:
        for item in folder.rglob('*'):
            if item.is_file():
                try:
                    total_size += item.stat().st_size
                except Exception:
                    continue
    except Exception as e:
        write_debug(f"Error calculating folder size for {folder}: {e}", channel="Warning")
    return total_size

def scan_directory(target: str, recursive: bool, depth: int, include_hidden: bool,
                   include_size: bool, include_date: bool, extra: dict, filter_pattern: str = None) -> List[Dict[str, Any]]:
    results = []
    target_path = Path(target)
    if not target_path.exists():
        write_debug(f"Target path {target} does not exist.", channel="Error")
        return results

    def scan(path: Path, current_depth: int):
        if depth is not None and current_depth > depth:
            return
        try:
            for entry in path.iterdir():
                if not include_hidden and entry.name.startswith('.'):
                    continue
                if filter_pattern and not re.search(filter_pattern, entry.name):
                    continue
                metadata = get_file_metadata(entry, include_size, include_date, extra)
                metadata['is_dir'] = entry.is_dir()
                results.append(metadata)
                if recursive and entry.is_dir():
                    scan(entry, current_depth + 1)
        except Exception as e:
            write_debug(f"Error scanning {path}: {e}", channel="Warning")
    scan(target_path, 0)
    return results