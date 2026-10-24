"""
Workspace resolution, manifest management, and path isolation for videocompress.
Follows INTEGRATION_CONTRACTS.md §4 and MEDIA_SAFETY_CONTRACT.md §1, §6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VideoWorkspace:
    """External artifact and cache workspace bound to a specific target."""

    root: Path
    inventory_db: Path
    trials_db: Path
    manifest_file: Path
    target: Path
    scope_id: str
    plans_dir: Path
    reports_dir: Path
    previews_dir: Path
    jobs_dir: Path
    journals_dir: Path


def resolve_workspace(
    target: Path | str,
    parent: Path | str | None = None,
) -> VideoWorkspace:
    """
    Resolve and initialize an isolated workspace directory for a target.

    Workspaces reside outside the target media tree under:
      <parent or target.parent>/.videocompress/<target_name>_<path_hash>/
    """
    target_path = Path(target).expanduser().resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"Target path does not exist: {target_path}")

    leaf = target_path.name
    if not leaf:
        raise ValueError("Cannot bind workspace to a filesystem root directory.")

    canonical_target_str = str(target_path).lower() if os.name == "nt" else str(target_path)
    path_hash = hashlib.sha256(canonical_target_str.encode("utf-8")).hexdigest()[:8]
    scope_id = f"{leaf}_{path_hash}"

    if parent:
        parent_path = Path(parent).expanduser().resolve()
        if parent_path.name == scope_id and parent_path.parent.name == ".videocompress":
            workspace_root = parent_path
        elif parent_path.name == ".videocompress":
            workspace_root = parent_path / scope_id
        else:
            workspace_root = parent_path / ".videocompress" / scope_id
    else:
        workspace_root = target_path.parent / ".videocompress" / scope_id

    # Verify workspace isolation
    if workspace_root == target_path:
        raise ValueError("Workspace root cannot be identical to target media path.")
    try:
        if target_path.is_dir() and workspace_root.is_relative_to(target_path):
            raise ValueError(f"Workspace root '{workspace_root}' must be outside target '{target_path}'.")
    except ValueError:
        pass

    inventory_db = workspace_root / "inventory.sqlite3"
    trials_db = workspace_root / "trials.sqlite3"
    manifest_file = workspace_root / "workspace.json"
    plans_dir = workspace_root / "plans"
    reports_dir = workspace_root / "reports"
    previews_dir = workspace_root / "previews"
    jobs_dir = workspace_root / "jobs"
    journals_dir = workspace_root / "journals"

    # Ensure directories exist
    for d in (workspace_root, plans_dir, reports_dir, previews_dir, jobs_dir, journals_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Write or verify manifest
    if not manifest_file.exists():
        manifest_data = {
            "schema_version": 1,
            "scope_id": scope_id,
            "target_canonical_path": str(target_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "owner": "videocompress",
        }
        manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    return VideoWorkspace(
        root=workspace_root,
        inventory_db=inventory_db,
        trials_db=trials_db,
        manifest_file=manifest_file,
        target=target_path,
        scope_id=scope_id,
        plans_dir=plans_dir,
        reports_dir=reports_dir,
        previews_dir=previews_dir,
        jobs_dir=jobs_dir,
        journals_dir=journals_dir,
    )
