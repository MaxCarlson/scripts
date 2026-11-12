"""External benchmark source and dependency management."""

from __future__ import annotations

from .manager import SourceManager
from .receipts import load_sources_lock, record_receipt, save_sources_lock
from .specs import InstallReceipt, InstalledSourcesLock, ResourceSpec
from .stores import (
    commit_staging_dir,
    create_staging_dir,
    ensure_store_layout,
    get_default_resource_root,
    hash_directory_tree,
    hash_file,
)

__all__ = [
    "InstallReceipt",
    "InstalledSourcesLock",
    "ResourceSpec",
    "SourceManager",
    "commit_staging_dir",
    "create_staging_dir",
    "ensure_store_layout",
    "get_default_resource_root",
    "hash_directory_tree",
    "hash_file",
    "load_sources_lock",
    "record_receipt",
    "save_sources_lock",
]
