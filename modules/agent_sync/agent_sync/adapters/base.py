from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentAdapter(abc.ABC):
    """Abstract base for provider-specific agent launchers."""

    repo_root: Path

    @property
    @abc.abstractmethod
    def agent_name(self) -> str:
        """Short provider identifier: 'claude', 'codex', 'gemini', 'local'."""

    @abc.abstractmethod
    def launch_args(self, *, prompt: str, task_id: str) -> list[str]:
        """Return argv list to launch the agent non-interactively."""

    @abc.abstractmethod
    def hook_env(self) -> dict[str, str]:
        """Return env vars the shell wrappers need to locate the repo root."""

    @abc.abstractmethod
    def config_files(self) -> list[Path]:
        """Return paths to provider config files written by agent-sync init."""

    def instruction_file(self) -> Path | None:
        """Return the provider's instruction file (CLAUDE.md / AGENTS.md / GEMINI.md)."""
        return None
