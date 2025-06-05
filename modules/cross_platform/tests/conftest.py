import sys
from pathlib import Path

# Ensure the cross_platform package is importable when running tests
_MODULES_DIR = Path(__file__).resolve().parents[2]
if str(_MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULES_DIR))
