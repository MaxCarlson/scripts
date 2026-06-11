"""Adapter factory."""

from pathlib import Path

from agent_sync.adapters.base import AgentAdapter
from agent_sync.adapters.command import CommandAdapter
from agent_sync.adapters.local import LocalAdapter
from agent_sync.config import WorkerSpec
from agent_sync.errors import ConfigError


def create_adapter(repo_root: Path, spec: WorkerSpec) -> AgentAdapter:
    """Create an adapter for a worker spec."""
    if spec.kind == "command":
        return CommandAdapter(repo_root=repo_root, spec=spec)
    if spec.kind == "local":
        return LocalAdapter(repo_root=repo_root, spec=spec)
    raise ConfigError(f"Unsupported worker kind '{spec.kind}' for worker '{spec.name}'.")
