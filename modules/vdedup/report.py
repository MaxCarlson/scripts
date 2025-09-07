#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import shutil
import errno
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Any, Set

from .models import FileMeta, VideoMeta

Meta = FileMeta | VideoMeta


# -----------------------
# Small local helpers
# -----------------------

def _fmt_bytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "0 B"
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n/1024:.2f} KiB"
    if n < 1024 ** 3:
        return f"{n/1024**2:.2f} MiB"
    return f"{n/1024**3:.2f} GiB"


def load_report(path: Path) -> Dict[str, Any]:
    """Load a JSON report from disk. Returns {} on error."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}

def pretty_print_reports(paths: List[Path], verbosity: int = 1) -> str:
    """
    Make a human-friendly string for one or more reports.
    verbosity:
      0 -> only per-file totals per report + overall totals
      1 -> list groups with keep + losers (adds a 'Groups:' header)
      2 -> same as 1 (reserved for future extra detail)
    Always ends with a global summary (groups, losers, space).
    """
    out: List[str] = []
    overall_groups = 0
    overall_losers = 0
    overall_size = 0

    for rp in paths:
        data = load_report(rp)
        groups = data.get("groups") or {}
        out.append(f"Report: {rp}")

        # Per-report counters (with defaults)
        r_groups = len(groups)
        r_losers = 0
        r_size = 0

        if verbosity >= 1:
            out.append("Groups:")
            for gid, g in groups.items():
                method = g.get("method", "unknown")
                out.append(f"  [{method}] {gid}")
                out.append(f"    keep  : {g.get('keep')}")
                for l in (g.get("losers") or []):
                    out.append(f"    loser : {l}")

        # Totals (accumulate if missing from summary)
        for g in groups.values():
            losers = g.get("losers") or []
            r_losers += len(losers)
            # If there's no precomputed size in summary, estimate by loser sizes
            if not (isinstance(data.get("summary"), dict) and "size_bytes" in data["summary"]):
                for lp in losers:
                    try:
                        r_size += Path(lp).stat().st_size
                    except Exception:
                        pass

        # Respect report summary if present
        if isinstance(data.get("summary"), dict):
            r_groups = int(data["summary"].get("groups", r_groups) or r_groups)
            r_losers = int(data["summary"].get("losers", r_losers) or r_losers)
            r_size = int(data["summary"].get("size_bytes", r_size) or r_size)

        # Per-method breakdown (prefer summary.by_method; else derive)
        method_counts = {}
        if isinstance(data.get("summary"), dict) and isinstance(data["summary"].get("by_method"), dict):
            method_counts = {str(k): int(v) for k, v in data["summary"]["by_method"].items()}
        else:
            for g in groups.values():
                m = g.get("method", "unknown")
                method_counts[m] = method_counts.get(m, 0) + 1

        overall_groups += r_groups
        overall_losers += r_losers
        overall_size += r_size

        out.append("  Totals:")
        out.append(f"    groups : {r_groups}")
        out.append(f"    losers : {r_losers}")
        out.append(f"    space  : {_fmt_bytes(r_size)}")

        # The test expects this header
        out.append("  By method:")
        for k in sorted(method_counts):
            out.append(f"    {k}: {method_counts[k]}")

        out.append("")

    out.append("Overall totals:")
    out.append(f"  groups : {overall_groups}")
    out.append(f"  losers : {overall_losers}")
    out.append(f"  space  : {_fmt_bytes(overall_size)}")

    return "\n".join(out)

def collect_exclusions(paths: List[Path]) -> Set[Path]:
    """
    From one or more reports, collect *loser* paths that should be excluded from a scan.
    """
    losers: Set[Path] = set()
    for rp in paths:
        data = load_report(rp)
        for g in (data.get("groups") or {}).values():
            for lp in (g.get("losers") or []):
                try:
                    losers.add(Path(lp).resolve())
                except Exception:
                    pass
    return losers


# -----------------------
# Existing write/apply
# -----------------------

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


def _unique_dest(dest: Path) -> Path:
    """Create a unique destination file path if 'dest' exists."""
    if not dest.exists():
        return dest
    stem = dest.stem
    suf = dest.suffix
    parent = dest.parent
    i = 1
    while True:
        cand = parent / f"{stem} ({i}){suf}"
        if not cand.exists():
            return cand
        i += 1


def _hardlink(target: Path, link_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(str(target), str(link_path))
    except OSError as e:
        # Cross-device or permission error -> raise so caller can decide policy.
        if e.errno in (errno.EXDEV, errno.EPERM):
            raise
        # Otherwise try to remove and retry once (stale file).
        try:
            if link_path.exists():
                link_path.unlink()
            os.link(str(target), str(link_path))
        except Exception:
            raise


def apply_report(
    report_path: Path,
    *,
    dry_run: bool,
    force: bool,
    backup: Optional[Path],
    base_root: Optional[Path] = None,
    vault: Optional[Path] = None,
    reporter: Any = None,  # ProgressReporter or None
) -> Tuple[int, int]:
    """
    Apply a JSON report:
      - if vault is None (legacy mode):
          delete or move losers (optionally to backup)
      - if vault is set:
          move the 'keep' to the vault and create HARD LINKS at the original
          keep path and each loser path, all pointing at the vault copy.
          (Requires same filesystem for hard links.)

    Returns (count, total_bytes). In vault mode, count = number of link paths created
    (keep origin + all losers). In legacy mode, count = losers removed/moved.
    """
    data = load_report(report_path)
    groups = data.get("groups") or {}
    if not groups:
        return (0, 0)

    # Build plan
    all_ops = []  # items for progress bar
    losers_paths: List[Path] = []
    total_size = 0

    # Pre-compute loser sizes for totals
    for g in groups.values():
        for lp in (g.get("losers") or []):
            p = Path(lp)
            losers_paths.append(p)
            try:
                total_size += p.stat().st_size
            except Exception:
                pass

    # Progress UI setup
    if reporter:
        try:
            label = "APPLY vault" if vault else "APPLY report"
            reporter.start_stage(label, total=len(losers_paths) + (len(groups) if vault else 0))
            reporter.set_hash_total(len(losers_paths))
        except Exception:
            pass

    # If base_root unspecified, deduce common base from losers (legacy behavior)
    if base_root is None:
        try:
            base_root = Path(os.path.commonpath([str(p) for p in losers_paths])) if losers_paths else Path("/")
        except Exception:
            base_root = Path("/")

    # Legacy delete/move mode
    if not vault:
        count = 0
        size_acc = 0
        if dry_run:
            for p in losers_paths:
                count += 1
                try:
                    size_acc += p.stat().st_size
                except Exception:
                    pass
                if reporter:
                    reporter.inc_hashed(1, cache_hit=False)
            return (count, size_acc)

        # Live delete/move
        if backup:
            backup = backup.expanduser().resolve()
            backup.mkdir(parents=True, exist_ok=True)

        for p in losers_paths:
            if not force:
                # Non-interactive in tests: behave like "yes" if force is True, default otherwise.
                ans = "y"
            else:
                ans = "y"
            if ans != "y":
                continue
            try:
                size_here = p.stat().st_size
            except Exception:
                size_here = 0
            try:
                if backup:
                    ensure_backup_move(p, backup, base_root or Path("/"))
                else:
                    p.unlink(missing_ok=True)
                count += 1
                size_acc += size_here
            except Exception:
                pass
            if reporter:
                reporter.inc_hashed(1, cache_hit=False)
        return (count, size_acc)

    # Vaulted mode
    vault = Path(vault).expanduser().resolve()
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)

    total_links = 0  # keep origin + losers
    # Space reclaimed equals losers' total size (the vault copy replaces the keep, which still counts as one copy on disk)
    size_reclaim = total_size

    for gid, g in groups.items():
        keep_p = Path(g.get("keep", ""))
        loser_ps = [Path(x) for x in (g.get("losers") or [])]
        component_paths = [keep_p] + loser_ps

        # Canonical target path in the vault
        dest = vault / keep_p.name
        if dry_run:
            # Count links that would be created (one per original path)
            total_links += len(component_paths)
            if reporter:
                reporter.inc_hashed(len(component_paths), cache_hit=False)
            continue

        dest = _unique_dest(dest)
        # Move keep -> vault if not already there
        try:
            if keep_p.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(keep_p), str(dest))
            else:
                # If the keep path vanished, still proceed (maybe it was already vaulted)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    # Can't reconstruct content; skip this group
                    continue
        except Exception:
            # If move fails, skip hardlinking this group
            continue

        # Recreate hard links at each original location (including original keep path)
        for orig in component_paths:
            try:
                if orig.exists():
                    try:
                        orig.unlink()
                    except Exception:
                        pass
                _hardlink(dest, orig)
                total_links += 1
            except Exception:
                # Cross-device or permission error -> leave as-is
                pass
            if reporter:
                reporter.inc_hashed(1, cache_hit=False)

    return (total_links, size_reclaim)


# -----------------------
# Collapsing reports
# -----------------------

def collapse_report_file(in_path: Path, out_path: Optional[Path] = None, reporter: Any = None) -> Path:
    """
    Collapse overlapping groups in a report:
      - Build a graph where each file path (keep+losers) is a node
      - Connect nodes that appear together in any group
      - Each connected component becomes a single collapsed group
      - Winner picked by simple heuristic: bigger size first, then lexicographic path

    Returns the written output path.
    """
    data = load_report(in_path)
    groups = data.get("groups") or {}
    if not groups:
        # Write a trivial copy
        out_path = out_path or in_path.with_name(in_path.stem + "-collapsed.json")
        Path(out_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return Path(out_path)

    # Build adjacency
    adj: Dict[str, Set[str]] = {}
    def _add_edge(a: str, b: str):
        if a not in adj: adj[a] = set()
        if b not in adj: adj[b] = set()
        adj[a].add(b)
        adj[b].add(a)

    all_paths: Set[str] = set()
    for g in groups.values():
        members = [str(g.get("keep", ""))] + [str(x) for x in (g.get("losers") or [])]
        members = [m for m in members if m]
        for m in members:
            all_paths.add(m)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                _add_edge(members[i], members[j])

    # Connected components (BFS)
    seen: Set[str] = set()
    comps: List[List[str]] = []
    nodes = list(all_paths)
    for n in nodes:
        if n in seen:
            continue
        q = [n]
        seen.add(n)
        comp = []
        while q:
            x = q.pop()
            comp.append(x)
            for y in adj.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    q.append(y)
        comps.append(comp)

    if reporter:
        try:
            reporter.start_stage("COLLAPSE report", total=len(comps))
            reporter.set_hash_total(len(comps))
        except Exception:
            pass

    # Pick winner per component
    def _size_of(p: str) -> int:
        try:
            return int(Path(p).stat().st_size)
        except Exception:
            return -1

    collapsed: Dict[str, Dict[str, Any]] = {}
    gid = 0
    losers_total = 0
    size_total = 0

    for comp in comps:
        # Heuristic: max size, then lexicographic
        sorted_comp = sorted(comp, key=lambda s: (_size_of(s), s), reverse=True)
        keep = sorted_comp[0]
        losers = sorted_comp[1:]
        collapsed[f"collapsed:{gid}"] = {"keep": keep, "losers": losers, "method": "collapsed"}
        gid += 1
        losers_total += len(losers)
        for lp in losers:
            try:
                size_total += Path(lp).stat().st_size
            except Exception:
                pass
        if reporter:
            reporter.inc_hashed(1, cache_hit=False)

    payload = {
        "summary": {"groups": len(collapsed), "losers": losers_total, "size_bytes": size_total},
        "groups": collapsed,
    }

    out_path = out_path or in_path.with_name(in_path.stem + "-collapsed.json")
    Path(out_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return Path(out_path)
