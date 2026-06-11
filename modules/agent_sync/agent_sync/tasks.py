"""Delegation task data structures."""

from dataclasses import dataclass
from pathlib import Path


VALID_TASK_TYPES = {
    "research",
    "summarize",
    "extract",
    "review",
    "verify",
    "plan",
    "classify",
    "brainstorm",
    "log-triage",
    "custom",
}

VALID_CONTEXT_LEVELS = {"brief", "standard", "full"}


@dataclass(frozen=True)
class DelegationTask:
    """A bounded unit of work delegated from a primary agent to a worker."""

    task_type: str
    prompt: str
    repo_root: Path
    context_level: str = "standard"
    title: str | None = None
    source_path: Path | None = None
    high_stakes: bool = False
    readonly: bool = True

    def validate(self) -> None:
        """Validate user-provided task metadata."""
        if self.task_type not in VALID_TASK_TYPES:
            raise ValueError(f"Unsupported task type '{self.task_type}'. Valid: {', '.join(sorted(VALID_TASK_TYPES))}")
        if self.context_level not in VALID_CONTEXT_LEVELS:
            raise ValueError(
                f"Unsupported context level '{self.context_level}'. Valid: {', '.join(sorted(VALID_CONTEXT_LEVELS))}"
            )
        if not self.prompt.strip():
            raise ValueError("Prompt cannot be empty.")
