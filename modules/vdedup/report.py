#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import FileMeta, VideoMeta

Meta = FileMeta | VideoMeta


# ------------------------
# Formatting / probe utils
# ------------------------

def _fmt_bytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "0 B"
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n/1024:.2f} KiB"
    if n < 1024**3:
        return f"{n/1024**2:.2f} MiB"
    return f"{n/1024**3:.2f} GiB"


def _fmt_hms(sec: Any) -> str:
    try:
        s = int(float(sec or 0))
        return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"
    except Exception:
        return "--:--:--"


def _probe_stats(path: Path) -> Dict[str, Any]:
    """
    Lightweight probe: duration, width, height, bitrates, size.
    Works even without ffprobe; then only 'size' is filled.
    """
    size = 0
    try:
        st = path.stat()
        size = int(st.st_size)
    except Exception:
        pass

    out: Dict[str, Any] = {
        "size": size,
        "duration": None,
        "width": None,
        "height": None,
        "overall_bitrate": None,
        "video_bitrate": None,
    }
    try:
        from .probe import run_ffprobe_json  # lazy import
        js = run_ffprobe_json(path)
        if js:
            try:
                out["duration"] = float(js.get("format", {}).get("duration", 0.0))
            except Exception:
                pass
            try:
                br = js.get("format", {}).get("bit_rate")
                out["overall_bitrate"] = int(br) if br is not None else None
            except Exception:
                pass
            for s in js.get("streams", []):
                if s.get("codec_type") == "video":
                    try:
                        out["video_bitrate"] = int(s.get("bit_rate")) if s.get("bit_rate") is not None else None
                    except Exception:
                        pass
                    try:
                        out["width"] = int(s.get("width") or 0) or None
                        out["height"] = int(s.get("height") or 0) or None
                    except Exception:
                        pass
                    break
    except Exception:
        pass
    return out


def _render_pair_diff(keep: Path, lose: Path, a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """Left-justified stat lines with deltas for KEEP vs LOSE."""
    lines: List[str] = []
    lines.append(f"KEEP: {keep}")
    lines.append(f"LOSE: {lose}")

    def col(label: str, av: Any, bv: Any, fmt=lambda x: str(x)):
        la = fmt(av) if av is not None else "—"
        lb = fmt(bv) if bv is not None else "—"
        delta_txt = ""
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            dv = av - bv
            if dv:
                sign = "+" if dv >= 0 else ""
                delta_txt = f"  Δ {sign}{dv}"
        lines.append(f"  {label:<14}: {la:<12} vs {lb:<12}{delta_txt}")

    col("duration", a.get("duration"), b.get("duration"), _fmt_hms)
    resa = f"{a.get('width','?')}x{a.get('height','?')}" if a.get("width") and a.get("height") else None
    resb = f"{b.get('width','?')}x{b.get('height','?')}" if b.get("width") and b.get("height") else None
    lines.append(f"  {'resolution':<14}: {resa or '—':<12} vs {resb or '—':<12}")
    col("v_bitrate", a.get("video_bitrate"), b.get("video_bitrate"))
    col("overall_bps", a.get("overall_bitrate"), b.get("overall_bitrate"))
    col("size", a.get("size"), b.get("size"), _fmt_bytes)
    return lines


# ----------------
# Report I/O utils
# ----------------

def load_report(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pretty_print_reports(paths: List[Path], verbosity: int = 1) -> str:
    out: List[str] = []
    tot_groups = tot_losers = tot_bytes = 0
    by_method_all: Dict[str, int] = {}

    for rp in paths:
        d = load_report(rp)
        out.append(f"Report: {rp}")
        out.append("Groups:")
        groups = d.get("groups") or {}
        by_method: Dict[str, int] = {}
        for gid, g in groups.items():
            method = g.get("method", "unknown")
            by_method[method] = by_method.get(method, 0) + 1
            by_method_all[method] = by_method_all.get(method, 0) + 1
            if verbosity >= 1:
                keep = g.get("keep", "")
                losers = g.get("losers") or []
                out.append(f"  [{method}] {gid}")
                out.append(f"    keep   : {keep}")
                out.append(f"    losers : {len(losers)}")
        # summary (use provided or compute minimal)
        s = d.get("summary") or {}
        groups_n = int(s.get("groups", len(groups)))
        losers_n = int(s.get("losers", sum(len((g or {}).get("losers") or []) for g in groups.values())))
        size_b = int(s.get("size_bytes", 0))
        out.append("")
        out.append("By method:")
        for k, v in sorted(by_method.items()):
            out.append(f"  {k:<8}: {v}")
        out.append("")
        out.append("Summary:")
        out.append(f"  groups : {groups_n}")
        out.append(f"  losers : {losers_n}")
        out.append(f"  space  : { _fmt_bytes(size_b) }")
        out.append("")

        tot_groups += groups_n
        tot_losers += losers_n
        tot_bytes += size_b

    out.append("Overall totals:")
    out.append(f"  groups : {tot_groups}")
    out.append(f"  losers : {tot_losers}")
    out.append(f"  space  : { _fmt_bytes(tot_bytes) }")
    return "\n".join(out)


def collect_exclusions(paths: List[Path]) -> set[Path]:
    ex: set[Path] = set()
    for rp in paths:
        try:
            d = load_report(rp)
            for g in (d.get("groups") or {}).values():
                for p in (g.get("losers") or []):
                    ex.add(Path(p))
        except Exception:
            continue
    return ex


# -------------
# Report writer
# -------------
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


# -----------------------
# Apply (delete/link/move)
# -----------------------
def ensure_backup_move(path: Path, backup_root: Path, base_root: Path) -> Path:
    rel = path.resolve().relative_to(base_root.resolve())
    dest = backup_root.joinpath(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def apply_report(
    report_path: Path,
    *,
    dry_run: bool,
    force: bool,
    backup: Optional[Path],
    base_root: Optional[Path] = None,
    vault: Optional[Path] = None,
    reporter: Any = None,
    verbosity: int = 0,
) -> Tuple[int, int]:
    """
    Apply a report:

      • If vault is None:
          - Delete (or backup-move) losers.
      • If vault is provided:
          - MOVE the group's winner (keep) into the vault.
          - RECREATE a HARDLINK at the original keep path pointing to the vaulted file.
          - For every loser path:
              - Delete/backup the loser.
              - Create a HARDLINK at the loser path pointing to the vaulted file.

    Returns (ops_count, total_bytes_saved_from_losers):
      - ops_count = number of paths linked (vault mode) or losers processed (delete/backup mode)

    Prints group-by-group details according to `verbosity`:
      V=2 – full stats and every planned operation
      V=1 – per-group summary
      V=0 – terse one-liners
    """
    data = load_report(report_path)
    groups: Dict[str, Any] = data.get("groups") or {}

    # Progress
    if reporter:
        reporter.start_stage("apply report", total=len(groups))

    # Determine total reclaimable bytes from losers
    total_size = 0
    if isinstance(data.get("summary"), dict) and "size_bytes" in data["summary"]:
        try:
            total_size = int(data["summary"]["size_bytes"])
        except Exception:
            total_size = 0
    if total_size == 0:
        for g in groups.values():
            for p in (g.get("losers") or []):
                try:
                    total_size += int(Path(p).stat().st_size)
                except Exception:
                    pass

    link_ops = 0
    losers_processed = 0

    if verbosity >= 0:
        print(f"Applying report: {report_path}")
        if dry_run:
            print("[DRY] No filesystem changes will be made.")
        if vault:
            print(f"Vault: {vault}")

    if not groups:
        return (0, 0)

    if backup:
        backup = backup.expanduser().resolve()
        if not dry_run:
            backup.mkdir(parents=True, exist_ok=True)

    if vault:
        vault = vault.expanduser().resolve()
        if not dry_run:
            vault.mkdir(parents=True, exist_ok=True)

    def _choose_vault_dest(vroot: Path, keep_path: Path, evidence: Optional[Dict[str, Any]]) -> Path:
        dest = vroot.joinpath(keep_path.name)
        if not dest.exists():
            return dest
        # Avoid collision — append short hash if available, else numeric suffix
        suffix = ""
        if evidence and isinstance(evidence.get("sha256"), str) and evidence["sha256"]:
            suffix = f".{evidence['sha256'][:8]}"
        i = 1
        while True:
            cand = vroot.joinpath(keep_path.stem + (suffix or f".{i}") + keep_path.suffix)
            if not cand.exists():
                return cand
            i += 1

    for gid, g in groups.items():
        keep = Path(g.get("keep", ""))
        losers = [Path(x) for x in (g.get("losers") or [])]
        method = g.get("method", "unknown")
        evidence = g.get("evidence") or {}

        # Per-group headers (V1+)
        if verbosity >= 1:
            print(f"[{method}] {gid}")
            print(f"  KEEP   : {keep}")
            print(f"  LOSERS : {len(losers)}")

        # Detailed diffs (V2)
        if verbosity >= 2 and keep:
            astats = _probe_stats(keep)
            for l in losers:
                bstats = _probe_stats(l)
                for line in _render_pair_diff(keep, l, astats, bstats):
                    print(f"    {line}")

        # Vault planning
        planned_vault_dest: Optional[Path] = None
        if vault and keep:
            planned_vault_dest = _choose_vault_dest(vault, keep, evidence)
            # unique original paths that will become links
            link_targets = [keep, *losers]
            link_targets = list(dict.fromkeys(link_targets))  # preserve order, dedupe exact duplicates
            if verbosity >= 1:
                print(f"  Vault  : MOVE -> {planned_vault_dest}")
                print(f"  Links  : {len(link_targets)} path(s) will point to the vaulted file")
        else:
            if verbosity >= 1:
                print("  Action : delete losers" + (" (backup move)" if backup else ""))

        # Execute (or dry-run)
        if dry_run:
            if vault and planned_vault_dest:
                print(f"    [DRY] MOVE {keep} -> {planned_vault_dest}")
                print(f"    [DRY] RECREATE HARDLINK at {keep} -> {planned_vault_dest}")
                for l in losers:
                    print(f"    [DRY] REPLACE {l} WITH HARDLINK -> {planned_vault_dest}")
                link_ops += 1 + len(losers)
            else:
                for l in losers:
                    if backup:
                        print(f"    [DRY] BACKUP MOVE {l} -> {backup}")
                    else:
                        print(f"    [DRY] DELETE {l}")
            losers_processed += len(losers)
        else:
            try:
                if vault and planned_vault_dest:
                    # Move keep → vault
                    planned_vault_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(keep), str(planned_vault_dest))
                    # Recreate hardlink where keep was
                    try:
                        if keep.exists():
                            keep.unlink()
                    except Exception:
                        pass
                    os.link(str(planned_vault_dest), str(keep))
                    link_ops += 1
                    # Replace losers with hardlinks to vault file
                    for l in losers:
                        try:
                            if backup:
                                ensure_backup_move(l, backup, base_root or Path("/"))
                            else:
                                l.unlink(missing_ok=True)
                        except Exception:
                            pass
                        try:
                            os.link(str(planned_vault_dest), str(l))
                            link_ops += 1
                        except Exception as e:
                            print(f"    WARN: failed to hardlink {l}: {e}")
                    losers_processed += len(losers)
                else:
                    # no vault: delete or backup losers
                    for l in losers:
                        if backup:
                            try:
                                ensure_backup_move(l, backup, base_root or Path("/"))
                            except Exception as e:
                                print(f"    WARN: backup move failed for {l}: {e}")
                                continue
                        else:
                            try:
                                l.unlink(missing_ok=True)
                            except Exception as e:
                                print(f"    WARN: delete failed for {l}: {e}")
                                continue
                        losers_processed += 1
            except Exception as e:
                print(f"  ERROR applying group {gid}: {e}")

        if verbosity == 0:
            # terse 1-liner per group
            keep_name = keep.name if keep else "(missing)"
            save_bytes = sum((l.stat().st_size if l.exists() else 0) for l in losers) if dry_run else 0
            links = (1 + len(losers)) if vault else 0
            print(f"[{method}] {gid}  keep: {keep_name}  <- {len(losers)} losers; +{links} links; save { _fmt_bytes(save_bytes) }")

        if reporter:
            reporter.inc_hashed(1, cache_hit=False)

    # Footer summary
    if verbosity >= 0:
        print("")
        print("Apply summary:")
        print(f"  groups            : {len(groups)}")
        print(f"  losers processed  : {losers_processed}")
        if vault:
            print(f"  hardlinks created : {link_ops}" + (" (dry-run planned)" if dry_run else ""))
        print(f"  space reclaimable : { _fmt_bytes(total_size) }")

    return (link_ops if vault else losers_processed, total_size)


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
        out_path = out_path or in_path.with_name(in_path.stem + "-collapsed.json")
        Path(out_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return Path(out_path)

    # Build adjacency
    adj: Dict[str, set[str]] = {}
    def _add_edge(a: str, b: str):
        if a not in adj: adj[a] = set()
        if b not in adj: adj[b] = set()
        adj[a].add(b)
        adj[b].add(a)

    all_paths: set[str] = set()
    for g in groups.values():
        members = [str(g.get("keep", ""))] + [str(x) for x in (g.get("losers") or [])]
        members = [m for m in members if m]
        for m in members:
            all_paths.add(m)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                _add_edge(members[i], members[j])

    # Connected components (BFS)
    seen: set[str] = set()
    comps: List[List[str]] = []
    for n in list(all_paths):
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
