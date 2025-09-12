import sys
from pathlib import Path

# Add the root project directory to the Python path.
# This ensures that pytest can find and import the 'sandr' package.
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
