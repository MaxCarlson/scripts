#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .models import FileMeta, VideoMeta

Meta = FileMeta | VideoMeta


def write_report(path: Path, winners: Dict[str, Tuple[Meta, List[Meta]]]):
    out = {}
    total_size = 0
    total_candidates = 0
    for gid, (keep, losers) in winners.items():
        out[gid] = {"keep": str(keep.path), "losers": [str(l.path) for l in losers]}
        total_candidates += len(losers)
        total_size += sum(getattr(l, "size", 0) or 0 for l in losers)
    payload = {"summary": {"groups": len(winners), "losers": total_candidates, "size_bytes": total_size}, "groups": out}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_backup_move(path: Path, backup_root: Path, base_root: Path) -> Path:
    rel = path.resolve().relative_to(base_root.resolve())
    dest = backup_root.joinpath(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def apply_report(report_path: Path, *, dry_run: bool, force: bool, backup: Optional[Path], base_root: Optional[Path] = None) -> Tuple[int, int]:
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    groups = data.get("groups") or {}
    loser_paths: List[Path] = []
    for g in groups.values():
        for p in g.get("losers", []):
            try:
                loser_paths.append(Path(p))
            except Exception:
                continue
    if not loser_paths:
        return (0, 0)

    if base_root is None:
        try:
            base_root = Path(os.path.commonpath([str(p) for p in loser_paths]))
        except Exception:
            base_root = Path("/")

    metas: List[FileMeta] = []
    for p in loser_paths:
        try:
            st = p.stat()
            metas.append(FileMeta(path=p, size=st.st_size, mtime=st.st_mtime))
        except FileNotFoundError:
            continue
        except Exception:
            metas.append(FileMeta(path=p, size=0, mtime=0))

    if not metas:
        return (0, 0)

    count = 0
    total = 0
    if dry_run:
        for m in metas:
            count += 1
            total += m.size
        return (count, total)

    if backup:
        backup = backup.expanduser().resolve()
        backup.mkdir(parents=True, exist_ok=True)

    for m in metas:
        if not force:
            ans = input(f"Delete '{m.path}'? [y/N]: ").strip().lower()
            if ans != "y":
                continue
        try:
            if backup:
                ensure_backup_move(m.path, backup, base_root or Path("/"))
            else:
                m.path.unlink(missing_ok=True)
            count += 1
            total += m.size
        except Exception:
            continue
    return (count, total)
