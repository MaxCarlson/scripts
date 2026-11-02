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


def pytest_configure(config):
    import os
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(__file__).resolve().parents[1] / ".pytest_tmp_root" / f"run-{os.getpid()}")
    state_dir = Path(config.option.basetemp) / "llm_monitor_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LLM_MONITOR_STATE_DIR"] = str(state_dir)
