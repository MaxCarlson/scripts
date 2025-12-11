#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Native worker: Python-based copy/move fallback for local transfers.

- Supports verbose stats, dry-run, replace/ignore-existing, and delete_source.
- Emits structured progress metrics for the manager dashboard.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Iterable, List, Tuple

from .base_worker import emit, RateCounter
from ..utils import resolve_local_target


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="native worker")
    ap.add_argument("--job", required=True, help="Path to job JSON.")
    return ap.parse_args()


def _iter_files(src: Path) -> Iterable[Path]:
    if src.is_file():
        yield src
        return
    if src.is_dir():
        for item in src.rglob("*"):
            if item.is_file():
                yield item


def _gather(src: Path) -> Tuple[List[Path], int]:
    files: List[Path] = []
    total = 0
    for path in _iter_files(src):
        files.append(path)
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return files, total


def native_copy(spec: dict) -> int:
    src = Path(spec["src"]).expanduser()
    dest_root = resolve_local_target(spec)
    replace = bool(spec.get("replace", False))
    delete_source = bool(spec.get("delete_source", False))
    dry_run = bool(spec.get("dry_run", False))
    if not dry_run:
        dest_root.mkdir(parents=True, exist_ok=True)

    files, total_bytes = _gather(src)
    files_total = len(files)

    emit(
        status="running",
        method="native",
        note=f"{'DRY RUN: ' if dry_run else ''}copying {files_total} items from {src} -> {dest_root}",
        bytes_total=total_bytes,
        files_total=files_total,
    )

    counter = RateCounter()
    bytes_done = 0
    files_done = 0
    started = time.time()

    for file_path in files:
        rel = file_path.relative_to(src) if file_path != src else Path(file_path.name)
        dest_path = dest_root / rel
        if not dry_run:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
        skip = dest_path.exists() and not replace

        if not dry_run and not skip:
            shutil.copy2(file_path, dest_path)

        if delete_source and not dry_run:
            try:
                file_path.unlink()
            except OSError:
                pass

        files_done += 1
        size = file_path.stat().st_size if file_path.exists() else 0
        bytes_done += size
        emit(
            status="running",
            method="native",
            current_file=str(rel),
            bytes_done=bytes_done,
            bytes_total=total_bytes,
            files_done=files_done,
            files_total=files_total,
            bytes_per_s=counter.update(bytes_done),
            eta_seconds=_estimate_eta(started, bytes_done, total_bytes),
        )

    emit(
        status="completed",
        method="native",
        bytes_done=bytes_done,
        bytes_total=total_bytes,
        files_done=files_done,
        files_total=files_total,
        duration=time.time() - started,
    )
    return 0


def _estimate_eta(started: float, done: int, total: int) -> float | None:
    if done <= 0 or total <= 0:
        return None
    elapsed = max(0.001, time.time() - started)
    rate = done / elapsed
    if rate <= 0:
        return None
    remaining = max(0, total - done)
    return remaining / rate


def main() -> int:
    args = parse_args()
    spec = json.loads(Path(args.job).read_text(encoding="utf-8"))
    return native_copy(spec)


if __name__ == "__main__":
    raise SystemExit(main())
