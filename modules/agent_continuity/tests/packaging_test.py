from __future__ import annotations

import tomllib
from pathlib import Path


def test_terminal_launcher_is_required_and_versions_match_metadata():
    repo_root = Path(__file__).resolve().parents[3]
    agent_metadata = tomllib.loads((repo_root / "modules/agent_continuity/pyproject.toml").read_text())
    terminal_metadata = tomllib.loads((repo_root / "modules/terminal_launcher/pyproject.toml").read_text())
    terminal_init = (repo_root / "modules/terminal_launcher/__init__.py").read_text()

    assert "terminal-launcher>=0.1.1,<0.2" in agent_metadata["project"]["dependencies"]
    assert terminal_metadata["project"]["version"] == "0.1.1"
    assert '__version__ = "0.1.1"' in terminal_init
    assert not any("agent-continuity" in dependency for dependency in terminal_metadata["project"]["dependencies"])
