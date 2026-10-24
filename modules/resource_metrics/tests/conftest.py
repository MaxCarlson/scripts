import sys
from pathlib import Path

# Ensure worktree's resource_metrics takes precedence over any editable install in virtualenv
MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.meta_path = [
    finder
    for finder in sys.meta_path
    if "resource_metrics" not in str(finder) and "resource_metrics" not in getattr(finder, "__module__", "")
]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))
for mod_name in list(sys.modules):
    if mod_name == "resource_metrics" or mod_name.startswith("resource_metrics."):
        del sys.modules[mod_name]
