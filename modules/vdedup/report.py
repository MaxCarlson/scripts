from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import FileMeta, VideoMeta
from .report_models import load_report_groups
from .report_viewer import render_reports_to_text

Meta = FileMeta | VideoMeta

# ------------------------
# Formatting / probe utils
# ------------------------

def _fmt_bytes(n: int) -> str:
    try:
        n = int(n or 0)
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
    if verbosity <= 0:
        # Minimal summary output
        tot_groups = tot_losers = tot_bytes = 0
        lines = []
        for rp in paths:
            report_groups = load_report_groups(rp)
            group_count = len(report_groups)
            loser_count = sum(g.duplicate_count for g in report_groups)
            reclaim_bytes = sum(g.reclaimable_bytes for g in report_groups)
            tot_groups += group_count
            tot_losers += loser_count
            tot_bytes += reclaim_bytes
            lines.append(f"{rp}: {group_count} groups, {loser_count} losers, {_fmt_bytes(reclaim_bytes)} reclaimable")
        lines.append("Overall:")
        lines.append(f"  groups : {tot_groups}")
        lines.append(f"  losers : {tot_losers}")
        lines.append(f"  space  : {_fmt_bytes(tot_bytes)}")
        return "\n".join(lines)

    color_output = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    return render_reports_to_text(paths, color=color_output)


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
    losers_total = 0
    by_method: Dict[str, int] = {}

    for gid, (keep, losers) in winners.items():
        keep_path = str(keep.path)
        loser_paths = [str(m.path) for m in losers]
        out[gid] = {
            "keep": keep_path,
            "losers": loser_paths,
            "method": getattr(keep, "method", "unknown"),
            "evidence": getattr(keep, "evidence", {}),
        }
        losers_total += len(losers)
        for m in losers:
            try:
                total_size += int(Path(m.path).stat().st_size)
            except Exception:
                pass
        by_method[out[gid]["method"]] = by_method.get(out[gid]["method"], 0) + 1

    payload = {
        "summary": {"groups": len(out), "losers": losers_total, "size_bytes": total_size, "by_method": by_method},
        "groups": out,
    }
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
    full_file_names: bool = False,   # NEW: show real paths if True; otherwise compact vset… aliases
) -> Tuple:
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

    Returns (ops_count, total_bytes_saved_from_losers)

    Prints group-by-group details according to `verbosity`:
      V=2 – full stats and every planned operation
      V=1 – per-group summary
      V=0 – terse one-liners
    """
    data = load_report(report_path)
    groups: Dict[str, Any] = data.get("groups") or {}

    # Determine a display base (common prefix) for pretty output
    all_paths: List[Path] = []
    for g in groups.values():
        if g.get("keep"):
            all_paths.append(Path(g["keep"]))
        for lp in g.get("losers") or []:
            all_paths.append(Path(lp))
    display_base: Optional[Path] = None
    if all_paths:
        try:
            display_base = Path(os.path.commonpath([str(p) for p in all_paths]))
        except Exception:
            display_base = None

    def rel(p: Path) -> str:
        if display_base:
            try:
                return str(Path(p).resolve().relative_to(display_base.resolve()))
            except Exception:
                return str(p)
        return str(p)

    # helpers for compact aliases
    def _friendly_gid(method: str, gid: str) -> str:
        if method == "collapsed" and gid.startswith("collapsed:"):
            try:
                n = int(gid.split(":", 1)[1])
                return f"Duplicate Set {n}"
            except Exception:
                return f"Duplicate Set ({gid})"
        return f"{gid}"

    def _set_number(method: str, gid: str, fallback_index: int) -> int:
        if method == "collapsed" and gid.startswith("collapsed:"):
            try:
                return int(gid.split(":", 1)[1])
            except Exception:
                pass
        # try to pull trailing digits
        digits = "".join(ch for ch in gid if ch.isdigit())
        try:
            if digits:
                return int(digits)
        except Exception:
            pass
        return fallback_index

    def _group_base(paths: List[str]) -> str:
        if not paths:
            return ""
        prefix = os.path.commonprefix(paths)
        i = max(prefix.rfind("/"), prefix.rfind("\\"))
        return prefix[: i + 1] if i >= 0 else ""

    def _first_folder(trimmed: str) -> str:
        if not trimmed:
            return ""
        for sep in ("/", "\\"):
            if sep in trimmed:
                return trimmed.split(sep, 1)[0]
        return ""

    # colors (only when TTY)
    def _c(s: str, code: str) -> str:
        if not os.isatty(1) or os.getenv("NO_COLOR"):
            return s
        return f"\x1b[{code}m{s}\x1b[0m"

    C_HDR  = "96;1"   # bright cyan bold
    C_KEEP = "92"     # green
    C_LOSE = "91"     # red
    C_VAULT= "95"     # magenta
    C_LINK = "94"     # bright blue
    C_REPL = "93"     # yellow for REPLACE
    C_FOLD = "36"     # cyan folder token
    C_DIM  = "2"

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
    set_sizes: List[int] = []

    if verbosity >= 0:
        print(f"Applying report: {report_path}")
        if display_base:
            print(f"Paths shown relative to: {display_base}")
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

    # iterate with enumeration for fallback numbering
    for idx, (gid, g) in enumerate(groups.items(), start=0):
        keep = Path(g.get("keep", "")) if g.get("keep") else None
        losers = [Path(x) for x in (g.get("losers") or [])]
        method = g.get("method", "unknown")
        evidence = g.get("evidence") or {}

        # set size stat
        set_sizes.append((1 if keep else 0) + len(losers))

        # Resolve display-relative strings
        rel_keep = rel(keep) if keep else ""
        rel_losers = [rel(l) for l in losers]
        gbase = _group_base([s for s in [rel_keep, *rel_losers] if s])
        def _trim(s: str) -> str:
            return s[len(gbase):] if gbase and s.startswith(gbase) else s

        # numbering + alias names (only for compact mode)
        set_num = _set_number(method, gid, idx)
        keep_ext = keep.suffix if keep else ".mp4"
        keep_alias = f"vset{set_num}_v1{keep_ext}"
        loser_aliases = [f"vset{set_num}_v{i+2}{p.suffix}" for i, p in enumerate(losers)]
        vault_short = f"{vault.name}/{keep_alias}" if vault else keep_alias

        def _fold_colored(path_rel_trim: str) -> str:
            folder = _first_folder(path_rel_trim)
            if not folder:
                return f"{keep_alias}"
            return f"{_c(folder, C_FOLD)}/{keep_alias}"

        def _fold_colored_loser(trim: str, alias: str) -> str:
            folder = _first_folder(trim)
            if not folder:
                return alias
            return f"{_c(folder, C_FOLD)}/{alias}"

        # Per-group headers (V1+)
        if verbosity >= 1:
            print(_c(f"[{_friendly_gid(method, gid)}]", C_HDR))
            if gbase:
                print(_c(f"  Base  : {gbase}", C_DIM))
            if keep:
                if full_file_names:
                    print(f"  KEEP  : {_c(_trim(rel_keep), C_KEEP)}")
                else:
                    print(f"  KEEP  : {_c(_fold_colored(_trim(rel_keep)), C_KEEP)}")
            print(f"  LOSERS: {len(losers)}")

        # Detailed diffs (V2) — these are meaningful only with real paths
        if verbosity >= 2 and keep:
            astats = _probe_stats(keep)
            for l, rl in zip(losers, rel_losers):
                bstats = _probe_stats(l)
                for line in _render_pair_diff(Path(_trim(rel_keep)), Path(_trim(rl)), astats, bstats):
                    print(f"    {line}")

        # Vault planning
        planned_vault_dest: Optional[Path] = None
        if vault and keep:
            planned_vault_dest = _choose_vault_dest(vault, keep, evidence)
            if verbosity >= 1:
                if full_file_names:
                    print(f"  Vault : {_c('MOVE', C_VAULT)} -> {rel(planned_vault_dest)}")
                else:
                    print(f"  Vault : {_c('MOVE', C_VAULT)} -> {vault_short}")
                print(f"  Links : {1 + len(losers)} path(s) will point to the vaulted file")
        else:
            if verbosity >= 1:
                print("  Action: delete losers" + (" (backup move)" if backup else ""))

        # Execute (or dry-run)
        if dry_run:
            if vault and planned_vault_dest and keep:
                if full_file_names:
                    print(f"    {_c('[DRY] MOVE', C_VAULT)} {_trim(rel_keep)} -> {rel(planned_vault_dest)}")
                    print(f"    {_c('[DRY] RECREATE HARDLINK', C_LINK)} at {_trim(rel_keep)} -> {rel(planned_vault_dest).rsplit('/',1)[0]}")
                    print(f"        {_c('WITH HARDLINK', C_LINK)} -> {planned_vault_dest.name}")
                else:
                    print(f"    {_c('[DRY] MOVE', C_VAULT)} {_fold_colored(_trim(rel_keep))} -> {vault_short}")
                    print(f"    {_c('[DRY] RECREATE HARDLINK', C_LINK)} at {_fold_colored(_trim(rel_keep))} -> {vault.name}")
                    print(f"        {_c('WITH HARDLINK', C_LINK)} -> {keep_alias}")
                for rl, la in zip(rel_losers, loser_aliases):
                    if full_file_names:
                        print(f"    {_c('[DRY] REPLACE', C_REPL)} {_trim(rl)}")
                        print(f"        {_c('WITH HARDLINK', C_LINK)} -> {planned_vault_dest.name}")
                    else:
                        print(f"    {_c('[DRY] REPLACE', C_REPL)} {_fold_colored_loser(_trim(rl), la)}")
                        print(f"        {_c('WITH HARDLINK', C_LINK)} -> {keep_alias}")
                link_ops += 1 + len(losers)
            else:
                for rl, la in zip(rel_losers, loser_aliases):
                    if backup:
                        if full_file_names:
                            print(f"    {_c('[DRY] BACKUP MOVE', C_DIM)} {_trim(rl)} -> {backup}")
                        else:
                            print(f"    {_c('[DRY] BACKUP MOVE', C_DIM)} {_fold_colored_loser(_trim(rl), la)} -> {backup}")
                    else:
                        if full_file_names:
                            print(f"    {_c('[DRY] DELETE', C_LOSE)} {_trim(rl)}")
                        else:
                            print(f"    {_c('[DRY] DELETE', C_LOSE)} {_fold_colored_loser(_trim(rl), la)}")
            losers_processed += len(losers)
        else:
            try:
                if vault and planned_vault_dest and keep:
                    planned_vault_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(keep), str(planned_vault_dest))
                    try:
                        if keep.exists():
                            keep.unlink()
                    except Exception:
                        pass
                    os.link(str(planned_vault_dest), str(keep))
                    link_ops += 1
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
                            print(f"    WARN: failed to hardlink {rel(l)}: {e}")
                    losers_processed += len(losers)
                else:
                    for l in losers:
                        if backup:
                            try:
                                ensure_backup_move(l, backup, base_root or Path("/"))
                            except Exception as e:
                                print(f"    WARN: backup move failed for {rel(l)}: {e}")
                                continue
                        else:
                            try:
                                l.unlink(missing_ok=True)
                            except Exception as e:
                                print(f"    WARN: delete failed for {rel(l)}: {e}")
                                continue
                        losers_processed += 1
            except Exception as e:
                print(f"  ERROR applying group {gid}: {e}")

        if verbosity == 0:
            # terse 1-liner per group
            keep_name = (_trim(rel_keep) if full_file_names else keep_alias) if keep else "(missing)"
            links = (1 + len(losers)) if vault else 0
            print(f"[{_friendly_gid(method, gid)}] keep: {keep_name}  <- {len(losers)} losers; +{links} links")

        if reporter:
            reporter.inc_hashed(1, cache_hit=False)

    # Footer summary
    if verbosity >= 0:
        print("")
        print(_c("Apply summary:", C_HDR))
        print(f"  groups            : {len(groups)}")
        print(f"  losers processed  : {losers_processed}")
        if vault:
            print(f"  hardlinks created : {link_ops}" + (" (dry-run planned)" if dry_run else ""))
        print(f"  space reclaimable : { _fmt_bytes(total_size) }")
        if set_sizes:
            s = sorted(set_sizes)
            n = len(s)
            median = s[n//2] if n % 2 == 1 else (s[n//2 - 1] + s[n//2]) / 2
            avg = sum(s) / n
            print(f"  set size (min/median/avg/max): {s[0]} / {median:.2f} / {avg:.2f} / {s[-1]}")

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
