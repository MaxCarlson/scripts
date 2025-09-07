#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Any

from .models import FileMeta, VideoMeta

Meta = FileMeta | VideoMeta


def _infer_method_from_gid(gid: str) -> str:
    """Infer grouping method from group-id prefix (e.g., 'hash:', 'meta:', 'phash:', 'subset:')."""
    if ":" in gid:
        prefix = gid.split(":", 1)[0].lower()
        if prefix in {"hash", "meta", "phash", "subset"}:
            return prefix
    return "unknown"


def _evidence_for_method(gid: str, cfg: Optional[Any]) -> Dict[str, Any]:
    """Return a lightweight evidence/config block suitable for saving with the group."""
    method = _infer_method_from_gid(gid)
    ev: Dict[str, Any] = {"method": method}
    if method == "hash":
        # If gid includes the digest, surface it
        try:
            ev["sha256"] = gid.split(":", 1)[1]
        except Exception:
            pass
    elif method == "meta":
        if cfg is not None:
            ev["duration_tolerance"] = getattr(cfg, "duration_tolerance", None)
            ev["same_res"] = getattr(cfg, "same_res", None)
            ev["same_codec"] = getattr(cfg, "same_codec", None)
            ev["same_container"] = getattr(cfg, "same_container", None)
    elif method == "phash":
        if cfg is not None:
            ev["phash_frames"] = getattr(cfg, "phash_frames", None)
            ev["per_frame_threshold"] = getattr(cfg, "phash_threshold", None)
    elif method == "subset":
        if cfg is not None:
            ev["min_ratio"] = getattr(cfg, "subset_min_ratio", None)
            ev["frame_threshold"] = getattr(cfg, "subset_frame_threshold", None)
    return ev


def write_report(path: Path, winners: Dict[str, Tuple[Meta, List[Meta]]], cfg: Optional[Any] = None):
    """
    Persist a report. Includes a summary and per-group info:
      - keep, losers
      - method (hash/meta/phash/subset)
      - evidence (parameters/digest helpful to understand how the match was made)
    """
    groups_out: Dict[str, Any] = {}
    total_size = 0
    total_losers = 0
    method_counts = {"hash": 0, "meta": 0, "phash": 0, "subset": 0, "unknown": 0}

    for gid, (keep, losers) in winners.items():
        losers_paths = [str(l.path) for l in losers]
        total_losers += len(losers)
        total_size += sum(int(getattr(l, "size", 0) or 0) for l in losers)
        method = _infer_method_from_gid(gid)
        method_counts[method] = method_counts.get(method, 0) + 1
        groups_out[gid] = {
            "keep": str(keep.path),
            "losers": losers_paths,
            "method": method,
            "evidence": _evidence_for_method(gid, cfg),
        }

    payload = {
        "summary": {
            "groups": len(winners),
            "losers": total_losers,
            "size_bytes": total_size,
            "by_method": method_counts,
        },
        "groups": groups_out,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_report(path: Path) -> Dict[str, Any]:
    """Load a single report (leniently)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"summary": {}, "groups": {}}
        if "groups" not in data or not isinstance(data["groups"], dict):
            data["groups"] = {}
        if "summary" not in data or not isinstance(data["summary"], dict):
            data["summary"] = {}
        return data
    except Exception:
        return {"summary": {}, "groups": {}}


def collect_exclusions(report_paths: Iterable[Path]) -> set[Path]:
    """
    Return a set of loser Paths from one or more reports.
    Paths are resolved (best-effort). Duplicates are removed.
    """
    losers: set[Path] = set()
    for rp in report_paths:
        data = load_report(rp)
        for g in (data.get("groups") or {}).values():
            for s in g.get("losers", []) or []:
                try:
                    losers.add(Path(s).expanduser().resolve())
                except Exception:
                    losers.add(Path(s))
    return losers


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n/1024:.2f} KiB"
    if n < 1024**3:
        return f"{n/1024**2:.2f} MiB"
    return f"{n/1024**3:.2f} GiB"


def summarize_report(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute a robust summary even for older reports that may lack fields.
    Returns: dict with keys groups, losers, size_bytes, by_method
    """
    groups = data.get("groups") or {}
    losers = 0
    size_bytes = 0
    by_method: Dict[str, int] = {}
    for gid, g in groups.items():
        losers_list = g.get("losers", []) or []
        losers += len(losers_list)
        method = g.get("method") or _infer_method_from_gid(str(gid))
        by_method[method] = by_method.get(method, 0) + 1
    if isinstance(data.get("summary"), dict) and "size_bytes" in data["summary"]:
        size_bytes = int(data["summary"]["size_bytes"] or 0)
    return {
        "groups": len(groups),
        "losers": losers,
        "size_bytes": size_bytes,
        "by_method": by_method,
    }


def pretty_print_reports(paths: List[Path], *, verbosity: int = 1) -> str:
    """
    Return a human-friendly string describing one or more reports.
    verbosity:
      0 = one-line totals
      1 = totals + per-report summary + method breakdown
      2 = verbose listing: for each report, print each group (keep + losers)
    """
    lines: List[str] = []
    grand_groups = 0
    grand_losers = 0
    grand_bytes = 0
    grand_by_method: Dict[str, int] = {}

    for rp in paths:
        data = load_report(rp)
        s = summarize_report(data)
        grand_groups += int(s["groups"])
        grand_losers += int(s["losers"])
        grand_bytes += int(s["size_bytes"])
        for k, v in (s["by_method"] or {}).items():
            grand_by_method[k] = grand_by_method.get(k, 0) + int(v)

        if verbosity >= 1:
            lines.append(f"Report: {rp}")
            lines.append(f"  Groups: {s['groups']}  |  Losers: {s['losers']}  |  Space to save: {_fmt_bytes(int(s['size_bytes']))}")
            if s["by_method"]:
                meth = ", ".join(f"{k}:{v}" for k, v in sorted(s["by_method"].items()))
                lines.append(f"  By method: {meth}")
            if verbosity >= 2:
                groups = data.get("groups") or {}
                for gid, g in groups.items():
                    method = g.get("method") or _infer_method_from_gid(str(gid))
                    keep = g.get("keep")
                    losers = g.get("losers") or []
                    lines.append(f"    [{method}] {gid}")
                    lines.append(f"      KEEP  : {keep}")
                    for lp in losers:
                        lines.append(f"      DELETE: {lp}")
            lines.append("")

    if verbosity == 0:
        lines.append(
            f"Total: groups={grand_groups}, losers={grand_losers}, space={_fmt_bytes(grand_bytes)}"
        )
    else:
        lines.append("Totals (all reports):")
        lines.append(f"  Groups: {grand_groups}  |  Losers: {grand_losers}  |  Space to save: {_fmt_bytes(grand_bytes)}")
        if grand_by_method:
            meth = ", ".join(f"{k}:{v}" for k, v in sorted(grand_by_method.items()))
            lines.append(f"  By method: {meth}")

    return "\n".join(lines)


def ensure_backup_move(path: Path, backup_root: Path, base_root: Path) -> Path:
    rel = path.resolve().relative_to(base_root.resolve())
    dest = backup_root.joinpath(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def apply_report(report_path: Path, *, dry_run: bool, force: bool, backup: Optional[Path], base_root: Optional[Path] = None) -> Tuple[int, int]:
    data = load_report(report_path)
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
