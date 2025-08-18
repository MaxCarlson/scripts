# file: video_dedupe.py
#!/usr/bin/env python3
"""
Video & File Deduplicator

Features:
- Exact duplicates by SHA-256 (any file type).
- Metadata-aware video duplicates (duration tolerance, resolution, codec/container, bitrates).
- Optional visual similarity via perceptual hashing (sampled frames with ffmpeg + Pillow + ImageHash).
- Flexible "keep" policy: choose which copy to keep (e.g., longest, highest resolution, highest bitrate, newest).
- Dry-run, JSON report, backup/quarantine moves, and confirmation prompts.

Cross-platform: Windows 11, WSL2 (Ubuntu), Termux (Android).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except Exception:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None

# ----------------------------
# Data Models
# ----------------------------

@dataclasses.dataclass(frozen=True)
class FileMeta:
    path: Path
    size: int
    mtime: float
    sha256: Optional[str] = None

@dataclasses.dataclass(frozen=True)
class VideoMeta(FileMeta):
    duration: Optional[float] = None           # seconds
    width: Optional[int] = None
    height: Optional[int] = None
    container: Optional[str] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    overall_bitrate: Optional[int] = None      # bps
    video_bitrate: Optional[int] = None        # bps
    # Optional visual signature
    phash_signature: Optional[Tuple[int, ...]] = None  # packed phash bits across sampled frames

    @property
    def resolution_area(self) -> int:
        if self.width and self.height:
            return self.width * self.height
        return 0


# ----------------------------
# Hashing / Probing Utilities
# ----------------------------

def sha256_file(path: Path, block_size: int = 1 << 18) -> Optional[str]:
    """Compute SHA-256; returns None on any error (permission, transient I/O)."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:
        return None


def _run_ffprobe_json(path: Path) -> Optional[dict]:
    """Invoke ffprobe and return parsed JSON or None if ffprobe missing/fails."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration,bit_rate,format_name",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,bit_rate",
            "-of", "json",
            str(path),
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return json.loads(out.decode("utf-8", errors="ignore"))
    except Exception:
        return None


def probe_video(path: Path) -> VideoMeta:
    """Return VideoMeta using ffprobe when available; otherwise basic FileMeta."""
    try:
        st = path.stat()
        size = st.st_size
        mtime = st.st_mtime
    except FileNotFoundError:
        return VideoMeta(path=path, size=0, mtime=0.0)

    fmt = _run_ffprobe_json(path)
    if not fmt:
        return VideoMeta(path=path, size=size, mtime=mtime)

    duration = None
    overall_bitrate = None
    container = None
    try:
        f = fmt.get("format", {})
        if "duration" in f:
            duration = float(f["duration"])
        if "bit_rate" in f and str(f["bit_rate"]).isdigit():
            overall_bitrate = int(f["bit_rate"])
        if "format_name" in f:
            container = str(f["format_name"])
    except Exception:
        pass

    width = height = None
    vcodec = acodec = None
    video_bitrate = None

    for s in fmt.get("streams", []):
        ctype = s.get("codec_type")
        if ctype == "video" and vcodec is None:
            vcodec = s.get("codec_name")
            w, h = s.get("width"), s.get("height")
            if isinstance(w, int) and isinstance(h, int):
                width, height = w, h
            br = s.get("bit_rate")
            if isinstance(br, str) and br.isdigit():
                video_bitrate = int(br)
            elif isinstance(br, int):
                video_bitrate = br
        elif ctype == "audio" and acodec is None:
            acodec = s.get("codec_name")

    return VideoMeta(
        path=path,
        size=size,
        mtime=mtime,
        duration=duration,
        width=width,
        height=height,
        container=container,
        vcodec=vcodec,
        acodec=acodec,
        overall_bitrate=overall_bitrate,
        video_bitrate=video_bitrate,
    )


def compute_phash_signature(path: Path, frames: int = 5) -> Optional[Tuple[int, ...]]:
    """
    Compute a compact perceptual signature by sampling N frames with ffmpeg and hashing via ImageHash.
    Returns a tuple of ints (one per frame; each int packs the phash bits) or None if unavailable.
    """
    try:
        from PIL import Image
        import imagehash
    except Exception:
        return None

    vm = probe_video(path)
    if not vm.duration or vm.duration <= 0:
        return None

    sig: List[int] = []
    fractions = [(i + 1) / (frames + 1) for i in range(frames)]

    for frac in fractions:
        ts = max(0.0, min(vm.duration * frac, max(0.0, vm.duration - 0.1)))
        try:
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", f"{ts:.3f}", "-i", str(path),
                "-frames:v", "1",
                "-f", "image2pipe",
                "-vcodec", "png",
                "pipe:1",
            ]
            raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            img = Image.open(io_bytes := __import__("io").BytesIO(raw))
            img.load()
            h = imagehash.phash(img)  # 64-bit
            sig.append(int(str(h), 16))
        except Exception:
            continue

    if len(sig) < max(2, frames // 2):
        return None
    return tuple(sig)


def phash_distance(sig_a: Sequence[int], sig_b: Sequence[int]) -> int:
    """Cumulative Hamming distance across corresponding 64-bit phash ints."""
    dist = 0
    for a, b in zip(sig_a, sig_b):
        x = a ^ b
        dist += x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
    return dist


# ----------------------------
# File Enumeration
# ----------------------------

def iter_files(root: Path, pattern: Optional[str], max_depth: Optional[int]) -> Iterable[Path]:
    """
    Yield all files under root respecting optional glob pattern and max_depth.
    max_depth: None means unlimited; 0 means only root.
    """
    root = Path(root).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        if max_depth is not None:
            rel = Path(dirpath).resolve().relative_to(root)
            depth = 0 if str(rel) == "." else len(rel.parts)
            if depth > max_depth:
                dirnames[:] = []
                continue
        for name in filenames:
            if pattern and not Path(name).match(pattern):
                continue
            yield Path(dirpath) / name


# ----------------------------
# Grouping Strategies
# ----------------------------

class Grouper:
    """Collect duplicate groups according to selected mode(s)."""

    def __init__(
        self,
        mode: str,
        duration_tolerance: float = 2.0,
        same_res: bool = False,
        same_codec: bool = False,
        same_container: bool = False,
        phash_frames: int = 5,
        phash_threshold: int = 12
    ):
        self.mode = mode  # 'hash' | 'meta' | 'phash' | 'all'
        self.duration_tolerance = duration_tolerance
        self.same_res = same_res
        self.same_codec = same_codec
        self.same_container = same_container
        self.phash_frames = phash_frames
        self.phash_threshold = phash_threshold

    def _collect_filemeta(self, path: Path) -> FileMeta:
        try:
            st = path.stat()
            return FileMeta(path=path, size=st.st_size, mtime=st.st_mtime)
        except Exception:
            return FileMeta(path=path, size=0, mtime=0)

    def _collect_videometa(self, path: Path, want_phash: bool) -> VideoMeta:
        vm = probe_video(path)
        if want_phash:
            sig = compute_phash_signature(path, frames=self.phash_frames)
            if sig:
                object.__setattr__(vm, "phash_signature", sig)
        return vm

    def collect(self, files: List[Path]) -> Dict[str, List[VideoMeta | FileMeta]]:
        """
        Returns groups keyed by an opaque ID; each group is a list of FileMeta/VideoMeta to consider duplicates.
        """
        groups: Dict[str, List[VideoMeta | FileMeta]] = {}
        want_meta = self.mode in ("meta", "phash", "all")
        want_phash = self.mode in ("phash", "all")

        metas: List[VideoMeta | FileMeta] = []
        lock = threading.Lock()

        def worker(p: Path):
            is_video = p.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"}
            if want_meta and is_video:
                m = self._collect_videometa(p, want_phash=want_phash)
            else:
                m = self._collect_filemeta(p)
            with lock:
                metas.append(m)

        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
            list(ex.map(worker, files))

        # Exact hash grouping
        if self.mode in ("hash", "all"):
            by_hash: Dict[str, List[VideoMeta | FileMeta]] = defaultdict(list)

            def ensure_hash(m: VideoMeta | FileMeta):
                if m.sha256 is None:
                    h = sha256_file(m.path)
                    if h:
                        if isinstance(m, VideoMeta):
                            object.__setattr__(m, "sha256", h)
                        else:
                            setattr(m, "sha256", h)

            with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
                list(ex.map(ensure_hash, metas))

            for m in metas:
                if m.sha256:
                    by_hash[m.sha256].append(m)

            for h, lst in by_hash.items():
                if len(lst) > 1:
                    groups[f"hash:{h}"] = lst

        # Metadata grouping
        if self.mode in ("meta", "all"):
            vids = [m for m in metas if isinstance(m, VideoMeta)]
            buckets: Dict[int, List[VideoMeta]] = defaultdict(list)
            tol = max(0.0, float(self.duration_tolerance))
            bucket_size = max(1.0, tol)
            for vm in vids:
                dur = vm.duration if vm.duration is not None else -1.0
                key = int(dur // bucket_size)
                buckets[key].append(vm)

            gid = 0
            for bkey, vlist in buckets.items():
                candidates = vlist + buckets.get(bkey - 1, []) + buckets.get(bkey + 1, [])
                candidates = list(set(candidates))
                parent = {id(v): id(v) for v in candidates}

                def find(x):
                    while parent[x] != x:
                        parent[x] = parent[parent[x]]
                        x = parent[x]
                    return x

                def union(a, b):
                    ra, rb = find(id(a)), find(id(b))
                    if ra != rb:
                        parent[rb] = ra

                def similar(a: VideoMeta, b: VideoMeta) -> bool:
                    if a.duration is None or b.duration is None:
                        return False
                    if abs(a.duration - b.duration) > tol:
                        return False
                    if self.same_res and (a.width != b.width or a.height != b.height):
                        return False
                    if self.same_codec and (a.vcodec != b.vcodec):
                        return False
                    if self.same_container and (a.container != b.container):
                        return False
                    return True

                for i in range(len(candidates)):
                    for j in range(i + 1, len(candidates)):
                        if similar(candidates[i], candidates[j]):
                            union(candidates[i], candidates[j])

                comps: Dict[int, List[VideoMeta]] = defaultdict(list)
                for v in candidates:
                    comps[find(id(v))].append(v)
                for comp in comps.values():
                    if len(comp) > 1:
                        groups[f"meta:{gid}"] = comp
                        gid += 1

        # Perceptual hashing grouping
        if self.mode in ("phash", "all"):
            vids = [m for m in metas if isinstance(m, VideoMeta) and m.phash_signature]
            visited = set()
            gid = 0
            for i, a in enumerate(vids):
                if i in visited:
                    continue
                group = [a]
                visited.add(i)
                for j in range(i + 1, len(vids)):
                    if j in visited:
                        continue
                    b = vids[j]
                    L = min(len(a.phash_signature or ()), len(b.phash_signature or ()))
                    if L < 2:
                        continue
                    dist = phash_distance(a.phash_signature[:L], b.phash_signature[:L])  # type: ignore
                    if dist <= self.phash_threshold * L:
                        group.append(b)
                        visited.add(j)
                if len(group) > 1:
                    groups[f"phash:{gid}"] = group
                    gid += 1

        return groups


# ----------------------------
# Keep/Deletion Policy
# ----------------------------

def make_keep_key(order: Sequence[str]):
    """
    Build a key function returning a tuple for sorting *descending by desirability*.
    Supported fields: longer, resolution, video_bitrate, newer, smaller, deeper
    """
    def key(m: FileMeta | VideoMeta):
        duration = m.duration if isinstance(m, VideoMeta) and m.duration is not None else -1.0
        res = m.resolution_area if isinstance(m, VideoMeta) else 0
        vbr = m.video_bitrate if isinstance(m, VideoMeta) and m.video_bitrate else 0
        newer = m.mtime
        smaller = -m.size
        depth = len(m.path.parts)

        mapping = {
            "longer": duration,
            "resolution": res,
            "video_bitrate": vbr,
            "newer": newer,
            "smaller": smaller,
            "deeper": depth,
        }
        return tuple(mapping.get(k, 0) for k in order)
    return key


def choose_winners(groups: Dict[str, List[FileMeta | VideoMeta]], keep_order: Sequence[str]) -> Dict[str, Tuple[FileMeta | VideoMeta, List[FileMeta | VideoMeta]]]:
    """
    For each group, pick the single 'winner' to keep; return mapping group_id -> (keep, losers)
    """
    keep_key = make_keep_key(keep_order)
    out = {}
    for gid, members in groups.items():
        sorted_members = sorted(members, key=lambda m: (keep_key(m), -len(m.path.as_posix())), reverse=True)
        keep = sorted_members[0]
        losers = sorted_members[1:]
        out[gid] = (keep, losers)
    return out


# ----------------------------
# I/O Operations
# ----------------------------

def ensure_backup_move(path: Path, backup_root: Path, base_root: Path) -> Path:
    """Move file under backup_root mirroring its relative path from base_root."""
    rel = path.resolve().relative_to(base_root.resolve())
    dest = backup_root.joinpath(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def delete_or_backup(losers: Iterable[FileMeta | VideoMeta], *, dry_run: bool, force: bool, backup_dir: Optional[Path], base_root: Path) -> Tuple[int, int]:
    """
    Returns (count, total_bytes)
    """
    count = 0
    total = 0
    for m in losers:
        try:
            size = m.size
        except Exception:
            size = 0
        if dry_run:
            _print(f"[DRY-RUN] Would remove: {m.path}")
            count += 1
            total += size
            continue

        if not force:
            ans = input(f"Delete '{m.path}'? [y/N]: ").strip().lower()
            if ans != "y":
                continue

        try:
            if backup_dir:
                ensure_backup_move(m.path, backup_dir, base_root)
            else:
                m.path.unlink(missing_ok=True)
            count += 1
            total += size
            _print(f"Removed: {m.path}")
        except Exception as e:
            _print(f"[ERROR] Could not remove {m.path}: {e}")
    return count, total


# ----------------------------
# Reporting / Output
# ----------------------------

def _print(msg: str):
    if console:
        console.print(msg)
    else:
        print(msg)


def print_groups(groups: Dict[str, List[FileMeta | VideoMeta]], winners: Optional[Dict[str, Tuple[FileMeta | VideoMeta, List[FileMeta | VideoMeta]]]] = None):
    if not groups:
        _print("[green]No duplicates detected.[/green]" if console else "No duplicates detected.")
        return

    if console:
        table = Table(title="Duplicate Groups", show_lines=True)
        table.add_column("Group", style="cyan", no_wrap=True)
        table.add_column("Keep", style="green")
        table.add_column("Others", style="magenta")
        for gid, members in groups.items():
            keep_str = "-"
            others_str = ", ".join(str(m.path) for m in members[1:])
            if winners and gid in winners:
                keep, losers = winners[gid]
                keep_str = str(keep.path)
                others_str = ", ".join(str(l.path) for l in losers)
            table.add_row(gid, keep_str, others_str)
        console.print(table)
    else:
        for gid, members in groups.items():
            print(f"[{gid}]")
            if winners and gid in winners:
                keep, losers = winners[gid]
                print(f"  KEEP:  {keep.path}")
                for l in losers:
                    print(f"  LOSE:  {l.path}")
            else:
                for m in members:
                    print(f"  {m.path}")
            print("-")


def write_report(path: Path, winners: Dict[str, Tuple[FileMeta | VideoMeta, List[FileMeta | VideoMeta]]]):
    out = {}
    total_size = 0
    total_candidates = 0
    for gid, (keep, losers) in winners.items():
        out[gid] = {
            "keep": str(keep.path),
            "losers": [str(l.path) for l in losers],
        }
        total_candidates += len(losers)
        total_size += sum(l.size for l in losers)
    payload = {
        "summary": {
            "groups": len(winners),
            "losers": total_candidates,
            "size_bytes": total_size,
        },
        "groups": out,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ----------------------------
# CLI
# ----------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Find and remove duplicate/similar videos & files.")
    p.add_argument("directory", help="Root directory to scan")

    # Mode
    p.add_argument("-M", "--mode", choices=["hash", "meta", "phash", "all"], default="hash",
                   help="Duplicate detection mode")
    p.add_argument("-p", "--pattern", help="Glob pattern to include (e.g. *.mp4)")
    p.add_argument("-r", "--recursive", nargs="?", const=-1, type=int,
                   help="Recurse: omit for none; use -1 for unlimited; or give a depth integer")

    # Metadata rules
    p.add_argument("--duration_tolerance", "-u", type=float, default=2.0, help="Duration tolerance in seconds")
    p.add_argument("--same_res", "-Rz", action="store_true", help="Require same resolution")
    p.add_argument("--same_codec", "-Rc", action="store_true", help="Require same video codec")
    p.add_argument("--same_container", "-RcN", action="store_true", help="Require same container/format")

    # Perceptual hashing
    p.add_argument("--phash_frames", "-F", type=int, default=5, help="Frames to sample for perceptual hashing")
    p.add_argument("--phash_threshold", "-T", type=int, default=12, help="Per-frame Hamming distance threshold (64-bit)")

    # Keep policy
    p.add_argument("--keep", "-k", type=str, default="longer,resolution,video_bitrate,newer,smaller,deeper",
                   help="Comma list: longer,resolution,video_bitrate,newer,smaller,deeper")

    # Actions & outputs
    p.add_argument("-x", "--dry-run", action="store_true", help="No changes; just print")
    p.add_argument("-f", "--force", action="store_true", help="Do not prompt for deletion")
    p.add_argument("-b", "--backup", type=str, help="Move losers to this folder instead of deleting")
    p.add_argument("-R", "--report", type=str, help="Write JSON report to this path")

    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    if not root.exists():
        _print(f"[ERROR] Directory not found: {root}")
        return 2

    if args.recursive is None:
        max_depth: Optional[int] = 0
    elif args.recursive == -1:
        max_depth = None
    else:
        max_depth = max(0, int(args.recursive))

    files = list(iter_files(root, args.pattern, max_depth))
    if not files:
        _print("No files matched.")
        return 0

    g = Grouper(
        mode=args.mode,
        duration_tolerance=args.duration_tolerance,
        same_res=args.same_res,
        same_codec=args.same_codec,
        same_container=args.same_container,
        phash_frames=args.phash_frames,
        phash_threshold=args.phash_threshold,
    )

    groups = g.collect(files)
    if not groups:
        _print("No duplicate groups found.")
        return 0

    keep_order = [t.strip() for t in args.keep.split(",") if t.strip()]
    winners = choose_winners(groups, keep_order)
    print_groups(groups, winners)

    if args.report:
        write_report(Path(args.report), winners)
        _print(f"Wrote report to: {args.report}")

    total_deleted = 0
    total_bytes = 0
    losers = [l for (_, ls) in winners.values() for l in ls]
    if losers:
        backup = Path(args.backup).expanduser().resolve() if args.backup else None
        c, s = delete_or_backup(losers, dry_run=args.dry_run, force=args.force, backup_dir=backup, base_root=root)
        total_deleted += c
        total_bytes += s

    _print(f"Candidates processed: {len(losers)}; removed/moved: {total_deleted}; size={total_bytes/1_048_576:.2f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
