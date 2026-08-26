from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


SaveSourceKind = Literal["files", "registry"]


@dataclass
class SaveSource:
    id: str
    kind: SaveSourceKind
    path: str
    origin: str = "manual"
    confidence: float = 1.0
    enabled: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SaveSource":
        return cls(**raw)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutableCandidate:
    path: str
    score: float
    origin: str
    enabled: bool = True
    observed_runs: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExecutableCandidate":
        return cls(**raw)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GameRecord:
    id: str
    name: str
    install_dirs: list[str] = field(default_factory=list)
    steam_app_id: int | None = None
    discovery_origins: list[str] = field(default_factory=list)
    executables: list[ExecutableCandidate] = field(default_factory=list)
    save_sources: list[SaveSource] = field(default_factory=list)
    save_states: dict[str, int] = field(default_factory=dict)
    state_overrides: dict[str, int] = field(default_factory=dict)
    tracked_playtime_seconds: float = 0.0
    imported_playtime_seconds: float = 0.0
    steam_reported_playtime_seconds: float = 0.0
    first_seen_at: str | None = None
    first_play_at: str | None = None
    last_play_at: str | None = None
    last_checked_at: str | None = None
    last_changed_at: str | None = None
    last_snapshot_id: str | None = None
    active_session_id: str | None = None
    exit_checkpoints: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = True
    status: str = "discovered"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GameRecord":
        data = dict(raw)
        data["executables"] = [ExecutableCandidate.from_dict(x) for x in data.get("executables", [])]
        data["save_sources"] = [SaveSource.from_dict(x) for x in data.get("save_sources", [])]
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["executables"] = [x.to_dict() for x in self.executables]
        raw["save_sources"] = [x.to_dict() for x in self.save_sources]
        return raw

    @property
    def effective_playtime_seconds(self) -> float:
        return max(
            self.imported_playtime_seconds + self.tracked_playtime_seconds,
            self.steam_reported_playtime_seconds,
        )

    def executable_paths(self) -> set[Path]:
        return {Path(item.path) for item in self.executables if item.enabled}


@dataclass
class SessionRecord:
    id: str
    game_id: str
    started_at: str
    ended_at: str | None = None
    duration_seconds: float = 0.0
    pids: list[int] = field(default_factory=list)
    executable_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManifestEntry:
    source_id: str
    relative_path: str
    blob_sha256: str
    size: int
    mtime_ns: int
    state_key: str
    state_index: int
    original_name: str
    friendly_name: str
    captured_at: str
    playtime_seconds: float

    @property
    def identity(self) -> str:
        return f"{self.source_id}:{self.relative_path}"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ManifestEntry":
        return cls(**raw)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotManifest:
    snapshot_id: str
    game_id: str
    created_at: str
    reason: str
    playtime_seconds: float
    session_id: str | None
    entries: list[ManifestEntry]
    changed_identities: list[str] = field(default_factory=list)
    deleted_identities: list[str] = field(default_factory=list)
    state_indices_changed: list[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SnapshotManifest":
        data = dict(raw)
        data["entries"] = [ManifestEntry.from_dict(x) for x in data.get("entries", [])]
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["entries"] = [x.to_dict() for x in self.entries]
        return raw
