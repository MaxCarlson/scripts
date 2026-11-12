"""Specifications and data structures for external benchmark resources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..benchmarks.schema import ResourceDeclaration


@dataclass(frozen=True)
class ResourceSpec:
    """Specification of an external resource to download or provision."""

    benchmark_id: str
    resource_type: str  # "harbor_registry" | "git_sparse" | "git" | "huggingface_dataset" | "python_environment" | "container_image"
    name: str
    url: str | None = None
    revision: str | None = None
    paths: tuple[str, ...] = ()
    checksums: dict[str, str] = field(default_factory=dict)
    env_requirements: tuple[str, ...] = ()
    optional: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        self.validate_safety()

    def validate_safety(self) -> None:
        """Validate that fields do not contain path traversal or dangerous characters."""
        for field_name, value in [
            ("benchmark_id", self.benchmark_id),
            ("name", self.name),
            ("revision", self.revision),
        ]:
            if value:
                if ".." in value or "/" in value or "\\" in value or ":" in value:
                    raise ValueError(f"Invalid or unsafe path character in {field_name}: {value!r}")
        for p in self.paths:
            if ".." in p or p.startswith("/") or p.startswith("\\"):
                raise ValueError(f"Invalid or unsafe path character in paths entry: {p!r}")

    def digest(self) -> str:
        """Deterministic fingerprint of this resource specification."""
        content = f"{self.benchmark_id}:{self.resource_type}:{self.name}:{self.url}:{self.revision}:{','.join(self.paths)}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_declaration(cls, benchmark_id: str, decl: ResourceDeclaration) -> ResourceSpec:
        """Create a ResourceSpec from a benchmark's ResourceDeclaration."""
        return cls(
            benchmark_id=benchmark_id,
            resource_type=decl.type,
            name=decl.name,
            url=decl.url,
            revision=decl.revision,
            paths=decl.paths,
            checksums=dict(decl.checksums),
            env_requirements=decl.env_requirements,
            optional=decl.optional,
            description=decl.description,
        )


@dataclass(frozen=True)
class InstallReceipt:
    """Cryptographically verifiable receipt of an installed external resource."""

    benchmark_id: str
    resource_name: str
    resource_type: str
    install_path: str
    revision: str | None
    spec_digest: str
    installed_at: str
    platform: str
    status: str  # "installed" | "verified" | "corrupted" | "failed"
    content_hash: str | None = None
    file_hashes: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstallReceipt:
        return cls(**data)


@dataclass
class InstalledSourcesLock:
    """Collection of all install receipts persisted in locks/installed-sources.json."""

    schema_version: str = "agent-benchmark-sources-v1"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    receipts: dict[str, InstallReceipt] = field(default_factory=dict)

    def get_receipt(self, benchmark_id: str, resource_name: str) -> InstallReceipt | None:
        key = f"{benchmark_id}:{resource_name}"
        return self.receipts.get(key)

    def add_receipt(self, receipt: InstallReceipt) -> None:
        key = f"{receipt.benchmark_id}:{receipt.resource_name}"
        self.receipts[key] = receipt
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "receipts": {k: v.to_dict() for k, v in self.receipts.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstalledSourcesLock:
        lock = cls(
            schema_version=data.get("schema_version", "agent-benchmark-sources-v1"),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )
        for k, v in data.get("receipts", {}).items():
            lock.receipts[k] = InstallReceipt.from_dict(v)
        return lock
