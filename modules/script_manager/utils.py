import os
import re
import sys
from importlib.util import find_spec
from pathlib import Path

def validate_python_name(name):
    """Ensures the provided name is a valid Python module name."""
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name) or name in sys.builtin_module_names:
        raise ValueError(f"'{name}' is not a valid Python module name!")

def check_name_conflicts(name):
    """Checks if a script/module name conflicts with existing executables or installed modules."""
    for path in os.getenv("PATH", "").split(os.pathsep):
        if Path(path, name).exists():
            raise ValueError(f"A command named '{name}' already exists in your PATH!")

    if find_spec(name):
        raise ValueError(f"A Python module named '{name}' is already installed!")
