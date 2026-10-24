"""
discover.py — Opt-in discovery of known toolkit SQLite databases without disk-wide crawling.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from db_manager.connections import get_readonly_connection


@dataclass(frozen=True)
class DiscoveredDatabase:
    name: str
    path: str
    module: str
    size_bytes: int
    is_accessible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_known_databases(repo_root: Path | None = None) -> list[DiscoveredDatabase]:
    """
    Finds known toolkit SQLite databases from predefined locations.

    Guarantees:
    - Never performs a recursive disk-wide crawl.
    - Never initializes missing databases or creates directories.
    - Never logs sensitive or private file paths.
    - Only includes files that exist and are verifiable SQLite files.
    """
    candidates: list[tuple[str, str, Path]] = []

    # If repo_root not provided, determine from file location
    if repo_root is None:
        current_dir = Path(__file__).resolve().parent
        # Look upward for repository root containing .git or modules
        root = current_dir
        while root.parent != root:
            if (root / ".git").exists() or (root / "modules").exists():
                break
            root = root.parent
        repo_root = root

    # 1. Project-local module candidates
    known_rel_paths = [
        ("script_logging", "Script Logging History", "modules/script_logging/history.sqlite3"),
        ("script_logging", "Script Logging History DB", "modules/script_logging/history.db"),
        ("runmux", "Runmux Runs Registry", "modules/runmux/registry.sqlite3"),
        ("mangadl", "MangaDL Library", "modules/mangadl/manga.db"),
        ("compresser", "Compresser Jobs", "modules/compresser/jobs.db"),
        ("knowledge_manager", "Knowledge Base", "modules/knowledge_manager/knowledge.db"),
        ("launcher", "Launcher Invocations", "invocations.sqlite3"),
        ("agent_sync", "Agent Sync Store", "modules/agent_sync/sync.db"),
    ]

    for module, name, rel in known_rel_paths:
        candidate_path = repo_root / rel
        candidates.append((module, name, candidate_path))

    # 2. User home/state candidates
    home = Path.home()
    user_state_candidates = [
        ("script_logging", "User Script Logging", home / ".local" / "state" / "scripts" / "history.sqlite3"),
        ("runmux", "User Runmux Registry", home / ".local" / "state" / "runmux" / "registry.sqlite3"),
        ("launcher", "User Launcher Invocations", home / ".local" / "state" / "scripts" / "invocations.sqlite3"),
    ]
    candidates.extend(user_state_candidates)

    discovered: list[DiscoveredDatabase] = []

    for module, name, path in candidates:
        if path.exists() and path.is_file():
            # Verify it is an accessible SQLite database
            accessible = False
            try:
                with get_readonly_connection(path, timeout=0.5) as conn:
                    # Quick verification query
                    conn.execute("SELECT 1;").fetchone()
                    accessible = True
            except Exception:
                accessible = False

            discovered.append(
                DiscoveredDatabase(
                    name=name,
                    path=str(path),
                    module=module,
                    size_bytes=path.stat().st_size,
                    is_accessible=accessible,
                )
            )

    return discovered
