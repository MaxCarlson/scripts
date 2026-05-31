from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from agent_sync.adapters.base import AgentAdapter


@dataclass
class ClaudeAdapter(AgentAdapter):
    """Adapter for Anthropic Claude Code CLI."""

    @property
    def agent_name(self) -> str:
        return "claude"

    def launch_args(self, *, prompt: str, task_id: str) -> list[str]:
        binary = shutil.which("claude") or "claude"
        return [binary, "-p", prompt, "--bare"]

    def hook_env(self) -> dict[str, str]:
        return {"CLAUDE_PROJECT_DIR": str(self.repo_root)}

    def config_files(self) -> list[Path]:
        return [self.repo_root / ".claude" / "settings.json"]

    def instruction_file(self) -> Path | None:
        return self.repo_root / "CLAUDE.md"
