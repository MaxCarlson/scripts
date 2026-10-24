"""Persistent per-project workspace state for ``runmux tui``."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WORKSPACE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WorkspaceState:
    """The user-opened process views and their independent viewport positions."""

    open_run_ids: list[str] = field(default_factory=list)
    active_run_id: str | None = None
    scroll_offsets: dict[str, int] = field(default_factory=dict)


class WorkspaceStateStore:
    """Read and atomically write one root- and app-scoped workspace file."""

    def __init__(self, state_dir: Path, root_dir: Path, *, app_id: str = "runmux") -> None:
        canonical_root = Path(root_dir).expanduser().resolve()
        root_key = str(canonical_root).casefold() if os.name == "nt" else canonical_root.as_posix()
        identity = f"{app_id}\0{root_key}".encode()
        digest = hashlib.sha256(identity).hexdigest()[:24]
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.root_dir = canonical_root
        self.app_id = app_id
        self.path = self.state_dir / "workspaces" / f"{digest}.json"

    def load(self) -> WorkspaceState:
        """Return saved state, using an empty workspace for missing/invalid data."""

        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return WorkspaceState()
        if not isinstance(raw, dict) or raw.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
            return WorkspaceState()
        ids = raw.get("open_run_ids")
        active = raw.get("active_run_id")
        offsets = raw.get("scroll_offsets")
        if not isinstance(ids, list) or not isinstance(offsets, dict):
            return WorkspaceState()
        open_ids = list(dict.fromkeys(item for item in ids if isinstance(item, str) and item))
        clean_offsets = {
            run_id: offset
            for run_id, offset in offsets.items()
            if isinstance(run_id, str) and isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0
        }
        return WorkspaceState(
            open_run_ids=open_ids,
            active_run_id=active if isinstance(active, str) and active in open_ids else None,
            scroll_offsets=clean_offsets,
        )

    def save(self, state: WorkspaceState) -> None:
        """Atomically persist the explicitly open views and viewport state."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "root_dir": str(self.root_dir),
            "app_id": self.app_id,
            "open_run_ids": list(dict.fromkeys(run_id for run_id in state.open_run_ids if run_id)),
            "active_run_id": state.active_run_id if state.active_run_id in state.open_run_ids else None,
            "scroll_offsets": {
                run_id: offset
                for run_id, offset in state.scroll_offsets.items()
                if isinstance(run_id, str) and isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0
            },
        }
        fd, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
