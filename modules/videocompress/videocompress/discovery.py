"""
Scoped media discovery with loop and workspace exclusion guards.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from .contracts import SourceIdentity

VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    ".mkv",
    ".mp4",
    ".m4v",
    ".webm",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".ts",
    ".m2ts",
    ".vob",
    ".ogv",
})

IGNORED_DIR_NAMES: frozenset[str] = frozenset({
    ".videocompress",
    ".compresser",
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp_root",
})


def discover_video_files(
    target: Path | str,
    workspace_root: Path | str | None = None,
) -> list[SourceIdentity]:
    """
    Discover all candidate video files under target path.

    Guards against symlink cycles, workspace artifacts, and hidden caches.
    Returns a sorted list of SourceIdentity records.
    """
    target_path = Path(target).expanduser().resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"Target path does not exist: {target_path}")

    ws_root_resolved = Path(workspace_root).expanduser().resolve() if workspace_root else None
    results: list[SourceIdentity] = []

    if target_path.is_file():
        if target_path.suffix.lower() in VIDEO_EXTENSIONS:
            st = target_path.stat()
            fp = f"{st.st_mtime_ns}:{st.st_size}"
            scope_id = target_path.parent.name
            results.append(
                SourceIdentity(
                    scope_id=scope_id,
                    relative_path=target_path.name,
                    canonical_path=str(target_path),
                    stat_fingerprint=fp,
                )
            )
        return results

    # Target is directory
    scope_id = target_path.name
    visited_real_dirs: set[str] = set()

    for root, dirs, files in os.walk(str(target_path), followlinks=False):
        current_root_path = Path(root).resolve()
        canonical_str = str(current_root_path).lower() if os.name == "nt" else str(current_root_path)

        # Symlink cycle / duplicate guard
        if canonical_str in visited_real_dirs:
            dirs.clear()
            continue
        visited_real_dirs.add(canonical_str)

        # Filter subdirectories in-place
        dirs[:] = [
            d for d in dirs
            if d.lower() not in IGNORED_DIR_NAMES
            and not (ws_root_resolved and (current_root_path / d).resolve() == ws_root_resolved)
        ]

        for file_name in files:
            file_path = current_root_path / file_name
            if file_path.suffix.lower() in VIDEO_EXTENSIONS:
                try:
                    st = file_path.stat()
                except (OSError, FileNotFoundError):
                    continue

                rel_path = str(file_path.relative_to(target_path))
                fp = f"{st.st_mtime_ns}:{st.st_size}"
                results.append(
                    SourceIdentity(
                        scope_id=scope_id,
                        relative_path=rel_path,
                        canonical_path=str(file_path),
                        stat_fingerprint=fp,
                    )
                )

    results.sort(key=lambda s: s.relative_path)
    return results
