from pathlib import Path
import os

def find_python_modules(root_dir: Path):
    """
    Finds Python module directories within a given root directory.
    A directory is considered a Python module if it contains an __init__.py file.
    """
    modules = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if '__init__.py' in filenames:
            # Check if it's a package (contains __init__.py)
            # and not a test directory or __pycache__
            if 'tests' not in Path(dirpath).parts and '__pycache__' not in Path(dirpath).parts:
                modules.append(Path(dirpath))
        # Exclude certain directories from further walking
        dirnames[:] = [d for d in dirnames if d not in ['__pycache__', 'venv', '.git', 'node_modules']]
    return modules
