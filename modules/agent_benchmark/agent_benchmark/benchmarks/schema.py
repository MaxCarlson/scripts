"""Schema definitions for benchmark catalog, datasets, cohorts, and resources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResourceDeclaration:
    """External resource requirement declaration (source, dataset, env, container)."""

    type: str  # "harbor_registry" | "git_sparse" | "git" | "huggingface_dataset" | "python_environment" | "container_image"
    name: str
    url: str | None = None
    revision: str | None = None
    paths: tuple[str, ...] = ()
    checksums: dict[str, str] = field(default_factory=dict)
    env_requirements: tuple[str, ...] = ()
    optional: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BackendDescriptor:
    """Execution backend capability descriptor."""

    id: str  # "harbor" | "direct_chat"
    name: str
    description: str
    capabilities: tuple[str, ...] = ()
    required_resources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScorerDescriptor:
    """Authoritative scoring adapter capability descriptor."""

    id: str  # "harbor_verifier" | "ifeval_official" | "lcb_official" | "mock_scorer"
    name: str
    version: str
    description: str
    protocol: str = "single-attempt-v1"
    required_resources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetDescriptor:
    """
    Dataset descriptor, backward-compatible with harbor.datasets.DatasetDescriptor.
    """

    id: str
    name: str
    version: str
    description: str
    supported_languages: tuple[str, ...]
    all_tasks: tuple[str, ...]
    default_scoring_protocol: str
    harbor_dataset: str | None = None
    source_repo: str | None = None
    source_revision: str | None = None
    default_tasks: tuple[str, ...] = ()
    # Additive metadata for unified benchmark catalog
    benchmark_id: str | None = None
    tags: tuple[str, ...] = ()
    install_state: str = "installed"  # "registered" | "installed" | "verified" | "blocked"
    readiness_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["supported_languages"] = list(self.supported_languages)
        data["all_tasks"] = list(self.all_tasks)
        data["total_tasks"] = len(self.all_tasks)
        data["default_tasks"] = list(self.default_tasks)
        data["tags"] = list(self.tags)
        return data


@dataclass(frozen=True)
class CohortDescriptor:
    """Predefined frozen or deterministic task cohort descriptor."""

    id: str
    dataset_id: str
    source_revision: str
    task_ids: tuple[str, ...]
    description: str = ""
    tags: tuple[str, ...] = ()
    seed: int | None = None
    scorer_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["task_ids"] = list(self.task_ids)
        data["tags"] = list(self.tags)
        return data


@dataclass(frozen=True)
class BenchmarkDescriptor:
    """High-level benchmark suite descriptor."""

    id: str  # e.g., "aider", "terminal-bench", "ifeval", "livecodebench"
    name: str
    version: str
    description: str
    implementation_type: str  # "harbor_agent" | "direct_model" | "synthetic"
    trusted_adapter_id: str
    supported_backends: tuple[str, ...]
    default_dataset: str | None = None
    resources: tuple[ResourceDeclaration, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["supported_backends"] = list(self.supported_backends)
        data["resources"] = [r.to_dict() for r in self.resources]
        data["limitations"] = list(self.limitations)
        return data
