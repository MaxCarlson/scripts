"""Filesystem store layout and atomic staging for external benchmark resources."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import time
from uuid import uuid4


def get_default_resource_root() -> Path:
    """
    Resolve the default external resource root outside of any Git-tracked scripts checkout.
    """
    env_root = os.environ.get("AGENT_BENCHMARK_RESOURCE_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
    elif platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            root = Path(local_app_data) / "agent-benchmark"
        else:
            root = Path.home() / ".local/share/agent-benchmark"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            root = Path(xdg_data) / "agent-benchmark"
        else:
            root = Path.home() / ".local/share/agent-benchmark"

    return root.resolve()


def ensure_store_layout(root: Path) -> dict[str, Path]:
    """Ensure standard external directories exist and return mapping."""
    dirs = {
        "root": root,
        "sources": root / "sources",
        "envs": root / "envs",
        "datasets": root / "datasets",
        "locks": root / "locks",
        "staging": root / "staging",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


def create_staging_dir(root: Path, tx_id: str | None = None) -> Path:
    """Create a unique staging directory outside the repository."""
    tx = tx_id or uuid4().hex
    staging = root / "staging" / tx
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def commit_staging_dir(staging_path: Path, target_path: Path) -> Path:
    """
    Atomically commit staged content into its target location with retries for Windows locks.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        # Remove or backup target if it already exists
        temp_backup = target_path.with_name(f".{target_path.name}.old.{uuid4().hex[:8]}")
        try:
            os.replace(target_path, temp_backup)
            shutil.rmtree(temp_backup, ignore_errors=True)
        except OSError:
            shutil.rmtree(target_path, ignore_errors=True)

    # Move staging to target
    last_err: Exception | None = None
    for attempt in range(10):
        try:
            os.replace(staging_path, target_path)
            return target_path
        except (PermissionError, OSError) as err:
            last_err = err
            time.sleep(0.05)

    # Fallback to copytree if replace failed
    try:
        shutil.copytree(staging_path, target_path, dirs_exist_ok=True)
        shutil.rmtree(staging_path, ignore_errors=True)
        return target_path
    except Exception as copy_err:
        raise OSError(f"Failed to commit staging {staging_path} to {target_path}: {last_err or copy_err}") from copy_err


def hash_file(path: Path) -> str:
    """Compute SHA-256 digest of a single file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def hash_directory_tree(dir_path: Path) -> dict[str, str]:
    """Compute dictionary of relative_path -> sha256 for all files in a tree."""
    hashes: dict[str, str] = {}
    if not dir_path.is_dir():
        return hashes
    for root, _, files in os.walk(dir_path):
        for f in sorted(files):
            full_p = Path(root) / f
            rel_p = full_p.relative_to(dir_path).as_posix()
            try:
                hashes[rel_p] = hash_file(full_p)
            except OSError:
                continue
    return hashes
