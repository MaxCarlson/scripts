from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .constants import COVER_STEM, IMAGE_SUFFIXES, METADATA_DIR_NAME
from .util import archive_replaced, atomic_write_bytes, sha256_file


def has_content_images(folder: Path) -> bool:
    try:
        for path in folder.rglob("*"):
            if METADATA_DIR_NAME in path.parts:
                continue
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.stat().st_size > 0:
                return True
    except OSError:
        return False
    return False


def existing_cover(metadata_dir: Path) -> Path | None:
    candidates = sorted(
        path
        for path in metadata_dir.glob(f"{COVER_STEM}.*")
        if path.is_file()
        and path.stem == COVER_STEM
        and path.suffix.lower() in IMAGE_SUFFIXES
        and path.stat().st_size > 0
    )
    return candidates[0] if candidates else None


def replace_cover(existing: Path | None, target: Path, payload: bytes, digest: str) -> Path:
    if existing is not None:
        if sha256_file(existing) == digest:
            return existing
        archive_replaced(existing)
    if sha256_file(target) != digest:
        atomic_write_bytes(target, payload)
    return target


def tree_stats_without_metadata(root: Path) -> tuple[int, int]:
    images = size = 0
    if not root.exists():
        return images, size
    for path in root.rglob("*"):
        if METADATA_DIR_NAME in path.parts:
            continue
        try:
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            size += path.stat().st_size
            if not path.name.endswith(".part") and path.suffix.lower() in IMAGE_SUFFIXES:
                images += 1
        except OSError:
            continue
    return images, size


def identity_without_metadata(root: Path) -> tuple[str, str]:
    for path in root.rglob("*") if root.exists() else ():
        if METADATA_DIR_NAME in path.parts:
            continue
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            relative = path.relative_to(root)
            site = relative.parts[0] if len(relative.parts) > 1 else "gallery"
            return site, path.parent.name
    return "", ""


def _fast_dir_stats(folder_path: str) -> tuple[int, int]:
    files = 0
    newest = 0
    stack = [folder_path]
    while stack:
        curr = stack.pop()
        try:
            with os.scandir(curr) as it:
                for entry in it:
                    if entry.name == METADATA_DIR_NAME:
                        continue
                    try:
                        if entry.is_file():
                            files += 1
                            mtime = entry.stat().st_mtime_ns
                            if mtime > newest:
                                newest = mtime
                        elif entry.is_dir():
                            stack.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue
    return files, newest


def snapshot_top_level(root: Path) -> dict[Path, tuple[int, int]]:
    snapshot: dict[Path, tuple[int, int]] = {}
    if not root.is_dir():
        return snapshot
    try:
        with os.scandir(str(root)) as it:
            for entry in it:
                if not entry.is_dir() or entry.name in {"_partial", METADATA_DIR_NAME}:
                    continue
                files, newest = _fast_dir_stats(entry.path)
                snapshot[Path(entry.path).resolve()] = (files, newest)
    except OSError:
        pass
    return snapshot


def changed_folders(
    before: Mapping[Path, tuple[int, int]],
    after: Mapping[Path, tuple[int, int]],
) -> list[Path]:
    return [folder for folder, state in after.items() if before.get(folder) != state and has_content_images(folder)]
