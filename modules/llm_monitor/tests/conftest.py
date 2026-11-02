import sys
from pathlib import Path

# Ensure worktree modules take precedence over any editable venv packages
_worktree_root = Path(__file__).resolve().parent.parent.parent.parent
_web_ui_tools_src = _worktree_root / "modules" / "web_ui_tools" / "src"
_llm_monitor_root = _worktree_root / "modules" / "llm_monitor"
_agent_benchmark_root = _worktree_root / "modules" / "agent_benchmark"

for path in [_agent_benchmark_root, _llm_monitor_root, _web_ui_tools_src]:
    if path.is_dir() and str(path) not in sys.path:
        sys.path.insert(0, str(path))
