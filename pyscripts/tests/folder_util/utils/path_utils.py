# folder_util/utils/path_utils.py

from pathlib import Path

def is_hidden(filepath: str) -> bool:
    p = Path(filepath)
    return p.name.startswith(".")