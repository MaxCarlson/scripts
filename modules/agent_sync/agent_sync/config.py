"""Worker registry configuration for agent_sync."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from agent_sync.errors import ConfigError


@dataclass(frozen=True)
class WorkerSpec:
    """Configuration for a callable LLM worker."""

    name: str
    kind: str
    enabled: bool
    capability_score: float
    cost: str
    rate_limited: bool
    context_limit: int
    strengths: tuple[str, ...] = field(default_factory=tuple)
    weaknesses: tuple[str, ...] = field(default_factory=tuple)
    command: tuple[str, ...] = field(default_factory=tuple)
    model: str | None = None
    local_url: str | None = None
    timeout_seconds: float = 300.0
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerSpec":
        """Create a worker spec from JSON data."""
        try:
            return cls(
                name=str(data["name"]),
                kind=str(data["kind"]),
                enabled=bool(data.get("enabled", True)),
                capability_score=float(data.get("capability_score", 0.5)),
                cost=str(data.get("cost", "unknown")),
                rate_limited=bool(data.get("rate_limited", True)),
                context_limit=int(data.get("context_limit", 32768)),
                strengths=tuple(str(item) for item in data.get("strengths", [])),
                weaknesses=tuple(str(item) for item in data.get("weaknesses", [])),
                command=tuple(str(item) for item in data.get("command", [])),
                model=None if data.get("model") is None else str(data.get("model")),
                local_url=None if data.get("local_url") is None else str(data.get("local_url")),
                timeout_seconds=float(data.get("timeout_seconds", 300.0)),
                notes=str(data.get("notes", "")),
            )
        except KeyError as error:
            raise ConfigError(f"Worker entry is missing required key: {error}") from error

    def to_dict(self) -> dict[str, Any]:
        """Convert this worker spec to JSON data."""
        return {
            "name": self.name,
            "kind": self.kind,
            "enabled": self.enabled,
            "capability_score": self.capability_score,
            "cost": self.cost,
            "rate_limited": self.rate_limited,
            "context_limit": self.context_limit,
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "command": list(self.command),
            "model": self.model,
            "local_url": self.local_url,
            "timeout_seconds": self.timeout_seconds,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class AgentSyncConfig:
    """Full agent_sync configuration."""

    default_worker: str
    workers: tuple[WorkerSpec, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentSyncConfig":
        """Create config from JSON data."""
        workers = tuple(WorkerSpec.from_dict(item) for item in data.get("workers", []))
        if not workers:
            raise ConfigError("Config must define at least one worker.")
        default_worker = str(data.get("default_worker") or workers[0].name)
        names = {worker.name for worker in workers}
        if default_worker not in names:
            raise ConfigError(f"default_worker '{default_worker}' is not defined in workers.")
        return cls(default_worker=default_worker, workers=workers)

    def to_dict(self) -> dict[str, Any]:
        """Convert config to JSON data."""
        return {
            "schema_version": 1,
            "default_worker": self.default_worker,
            "workers": [worker.to_dict() for worker in self.workers],
        }

    def get_worker(self, name: str) -> WorkerSpec:
        """Return a worker by name."""
        for worker in self.workers:
            if worker.name == name:
                return worker
        raise ConfigError(f"Unknown worker '{name}'. Available: {', '.join(self.worker_names())}")

    def worker_names(self) -> list[str]:
        """Return configured worker names."""
        return [worker.name for worker in self.workers]

    def enabled_workers(self) -> list[WorkerSpec]:
        """Return enabled workers."""
        return [worker for worker in self.workers if worker.enabled]


def default_config() -> AgentSyncConfig:
    """Return the default worker registry."""
    workers = (
        WorkerSpec(
            name="claude",
            kind="command",
            enabled=True,
            capability_score=0.95,
            cost="paid-rate-limited",
            rate_limited=True,
            context_limit=200000,
            strengths=("architecture", "multi-file coding", "review", "planning", "high-stakes verification"),
            weaknesses=("rate limits",),
            command=("claude", "-p", "{prompt}", "--bare"),
            timeout_seconds=900,
            notes="Equivalent-to-primary class worker when rate limit budget allows.",
        ),
        WorkerSpec(
            name="codex",
            kind="command",
            enabled=True,
            capability_score=0.92,
            cost="paid-rate-limited",
            rate_limited=True,
            context_limit=200000,
            strengths=("code generation", "patch review", "test generation", "repo reasoning"),
            weaknesses=("rate limits",),
            command=("codex", "exec", "{prompt}"),
            timeout_seconds=900,
            notes="Strong coding worker. Validate installed CLI syntax with `agent-sync doctor`.",
        ),
        WorkerSpec(
            name="gemini",
            kind="command",
            enabled=True,
            capability_score=0.88,
            cost="paid-rate-limited",
            rate_limited=True,
            context_limit=1000000,
            strengths=("long-context research", "summarization", "code review", "gap analysis"),
            weaknesses=("may need strict output contracts",),
            command=("gemini", "--prompt-file", "{prompt_file}"),
            timeout_seconds=900,
            notes="Best default for long-context research/review when available.",
        ),
        WorkerSpec(
            name="copilot",
            kind="command",
            enabled=False,
            capability_score=0.75,
            cost="paid-rate-limited",
            rate_limited=True,
            context_limit=32768,
            strengths=("small coding tasks", "alternate review perspective"),
            weaknesses=("CLI syntax varies by installation", "not enabled by default"),
            command=("gh", "copilot", "suggest", "{prompt}"),
            timeout_seconds=600,
            notes="Disabled by default because GitHub Copilot CLI workflows vary.",
        ),
        WorkerSpec(
            name="local-lmstudio",
            kind="local",
            enabled=True,
            capability_score=0.70,
            cost="local-unlimited",
            rate_limited=False,
            context_limit=32768,
            strengths=("cheap iteration", "summaries", "classification", "log triage", "draft review"),
            weaknesses=("less reliable for critical correctness", "depends on loaded local model"),
            model=None,
            local_url="http://localhost:1234/v1",
            timeout_seconds=300,
            notes="Uses scripts/modules/llm_local when installed; ideal for token-heavy low-risk tasks.",
        ),
    )
    return AgentSyncConfig(default_worker="local-lmstudio", workers=workers)


def load_config(path: Path) -> AgentSyncConfig:
    """Load config from path, returning defaults if it does not exist."""
    if not path.exists():
        return default_config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"Invalid JSON config at {path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"Config at {path} must be a JSON object.")
    return AgentSyncConfig.from_dict(data)


def save_config(config: AgentSyncConfig, path: Path, *, force: bool = False) -> None:
    """Save config to path."""
    if path.exists() and not force:
        raise ConfigError(f"Config already exists: {path}. Use --force to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8")
