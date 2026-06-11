"""Base worker adapter interfaces."""

from dataclasses import dataclass
from pathlib import Path

from agent_sync.config import WorkerSpec


@dataclass(frozen=True)
class WorkerResult:
    """Result of invoking a worker."""

    worker: str
    output: str
    exit_code: int | None
    duration_seconds: float
    status: str
    error: str | None = None


@dataclass
class AgentAdapter:
    """Base adapter for provider-specific worker launchers."""

    repo_root: Path
    spec: WorkerSpec

    @property
    def agent_name(self) -> str:
        """Return the short provider identifier."""
        return self.spec.name

    def run(self, prompt: str, *, task_type: str, context_level: str) -> WorkerResult:
        """Run the worker and return output."""
        raise NotImplementedError

    def launch_args(self, *, prompt: str, task_id: str) -> list[str]:
        """Compatibility hook for older agent_sync plans."""
        del prompt, task_id
        return list(self.spec.command)

    def hook_env(self) -> dict[str, str]:
        """Return environment variables used by shell hook wrappers."""
        return {"AGENT_SYNC_REPO_ROOT": str(self.repo_root)}

    def config_files(self) -> list[Path]:
        """Return provider config files managed by agent_sync init."""
        return []

    def instruction_file(self) -> Path | None:
        """Return the provider instruction file path, if any."""
        return None
