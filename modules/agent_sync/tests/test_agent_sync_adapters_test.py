from pathlib import Path

from agent_sync.adapters.base import AgentAdapter
from agent_sync.adapters.claude import ClaudeAdapter


def test_claude_adapter_name() -> None:
    adapter = ClaudeAdapter(repo_root=Path("/tmp/repo"))
    assert adapter.agent_name == "claude"


def test_claude_adapter_launch_args_non_interactive() -> None:
    adapter = ClaudeAdapter(repo_root=Path("/tmp/repo"))
    args = adapter.launch_args(prompt="do the thing", task_id="T001")
    assert "claude" in args[0]
    assert "-p" in args or "--print" in args


def test_claude_adapter_hook_env_contains_project_dir() -> None:
    adapter = ClaudeAdapter(repo_root=Path("/tmp/repo"))
    env = adapter.hook_env()
    assert "CLAUDE_PROJECT_DIR" in env
    assert env["CLAUDE_PROJECT_DIR"] == "/tmp/repo"


def test_claude_adapter_config_files() -> None:
    adapter = ClaudeAdapter(repo_root=Path("/tmp/repo"))
    files = adapter.config_files()
    assert any(".claude/settings.json" in str(f) for f in files)
