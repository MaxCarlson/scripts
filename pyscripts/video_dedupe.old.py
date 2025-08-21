# file: video_dedupe.py
#!/usr/bin/env python3
"""
Video & File Deduplicator

- Exact duplicates by SHA-256 (any file type)
- Metadata-aware video duplicates (duration tolerance, resolution, codec/container, bitrates)
- Optional perceptual hashing (phash) for visually-similar videos
- Safe actions: dry-run, backup/quarantine, prompts
- Presets: --preset {low,medium,high}
- Optional live dashboard via --live (uses TermDash module provided by user)
- Apply an existing JSON report via --apply-report to delete/move listed losers

Cross-platform: Windows 11 (PowerShell), WSL2, Termux
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

# ----------------------------
# Optional UI libs
# ----------------------------
try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except Exception:
    RICH_AVAILABLE = False
console = Console() if RICH_AVAILABLE else None

# Try to import TermDash from ../modules (user-provided)
TERMDASH_AVAILABLE = False
TermDash = Line = Stat = None  # type: ignore
try:
    _MOD_DIR = Path(__file__).resolve().parent.parent / "modules"
    if _MOD_DIR.exists():
        sys.path.insert(0, str(_MOD_DIR))
    from termdash import TermDash, Line, Stat  # type: ignore
    TERMDASH_AVAILABLE = True
except Exception:
    TERMDASH_AVAILABLE = False

# ----------------------------
# Models
# ----------------------------

@dataclasses.dataclass(frozen=True)
class FileMeta:
    path: Path
    size: int
    mtime: float
    sha256: Optional[str] = None

@dataclasses.dataclass(frozen=True)
class VideoMeta(FileMeta):
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    container: Optional[str] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    overall_bitrate: Optional[int] = None
    video_bitrate: Optional[int] = None
    phash_signature: Optional[Tuple[int, ...]] = None

    @property
    def resolution_area(self) -> int:
        if self.width and self.height:
            return self.width * self.height
        return 0

# ----------------------------
# Utilities
# ----------------------------

def _print(msg: str):
    if console:
        console.print(msg)
    else:
        print(msg)

def sha256_file(path: Path, block_size: int = 1 << 18) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:
        return None

def _run_ffprobe_json(path: Path) -> Optional[dict]:
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
    try:
        from PIL import Image
        import imagehash
        import io
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
            img = Image.open(io.BytesIO(raw))
            img.load()
            h = imagehash.phash(img)  # 64-bit
            sig.append(int(str(h), 16))
        except Exception:
            continue

    if len(sig) < max(2, frames // 2):
        return None
    return tuple(sig)

def phash_distance(sig_a: Sequence[int], sig_b: Sequence[int]) -> int:
    dist = 0
    for a, b in zip(sig_a, sig_b):
        x = a ^ b
        dist += x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
    return dist

# ----------------------------
# Live progress (optional)
# ----------------------------

class ProgressReporter:
    """Thread-safe counters + optional TermDash updates."""
    def __init__(self, enable_dash: bool, refresh_rate: float = 0.2):
        self.enable_dash = enable_dash and TERMDASH_AVAILABLE and sys.stdout.isatty()
        self.refresh_rate = max(0.05, float(refresh_rate))
        self.lock = threading.Lock()
        self.start_ts = time.time()

        # Counters
        self.total_files = 0
        self.scanned_files = 0
        self.video_files = 0
        self.bytes_seen = 0
        self.hash_done = 0
        self.phash_sigs = 0
        self.groups_hash = 0
        self.groups_meta = 0
        self.groups_phash = 0

        # Dashboard
        self.dash: Optional[TermDash] = None  # type: ignore
        self._ticker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

        # Pre-built lines (created in start())
        self._line_hdr = None
        self._line_scan = None
        self._line_groups = None
        self._line_results = None

    def start(self):
        if not self.enable_dash:
            return
        self.dash = TermDash(refresh_rate=self.refresh_rate, enable_separators=True, reserve_extra_rows=2)

        # Build lines
        self._line_hdr = Line("hdr", stats=[Stat("title", "Video Deduper — Live", format_string="{}")], style="header")
        self._line_scan = Line("scan", stats=[
            Stat("elapsed", "--:--:--", prefix="Elapsed: ", no_expand=True, display_width=9),
            Stat("files", (0, 0), prefix="Files: ", format_string="{}/{}", no_expand=True, display_width=13),
            Stat("videos", 0, prefix="Videos: ", format_string="{}", no_expand=True, display_width=12),
            Stat("hashed", 0, prefix="Hashed: ", format_string="{}", no_expand=True, display_width=12),
            Stat("phsig", 0, prefix="pHash sigs: ", format_string="{}", no_expand=True, display_width=14),
        ])
        self._line_groups = Line("groups", stats=[
            Stat("g_hash", 0, prefix="Hash groups: ", format_string="{}", no_expand=True, display_width=16),
            Stat("g_meta", 0, prefix="Meta groups: ", format_string="{}", no_expand=True, display_width=16),
            Stat("g_phash", 0, prefix="pHash groups: ", format_string="{}", no_expand=True, display_width=16),
            Stat("g_total", 0, prefix="Total groups: ", format_string="{}", no_expand=True, display_width=16),
        ])
        self._line_results = Line("results", stats=[
            Stat("losers", 0, prefix="Losers: ", format_string="{}", no_expand=True, display_width=12),
            Stat("bytes", 0, prefix="Bytes: ", format_string="{}", no_expand=True, display_width=12),
        ])

        # Start dashboard
        self.dash.__enter__()  # context-like start
        self.dash.add_line("hdr", self._line_hdr, at_top=True)
        self.dash.add_line("scan", self._line_scan)
        self.dash.add_line("groups", self._line_groups)
        self.dash.add_line("results", self._line_results)

        # background ticker to update elapsed
        self._ticker = threading.Thread(target=self._tick_loop, daemon=True)
        self._ticker.start()
        self.flush()  # initial paint

    def stop(self):
        if not self.enable_dash:
            return
        self._stop_evt.set()
        if self._ticker:
            self._ticker.join(timeout=1)
        if self.dash:
            try:
                self.dash.__exit__(None, None, None)
            except Exception:
                pass

    # ---- tick & flush ----
    def _tick_loop(self):
        while not self._stop_evt.is_set():
            self._set_elapsed()
            time.sleep(self.refresh_rate)

    def _set_elapsed(self):
        if not self.enable_dash or not self.dash:
            return
        elapsed = int(time.time() - self.start_ts)
        self.dash.update_stat("scan", "elapsed", f"{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}")

    def flush(self):
        if not self.enable_dash or not self.dash:
            return
        with self.lock:
            self._set_elapsed()
            self.dash.update_stat("scan", "files", (self.scanned_files, self.total_files))
            self.dash.update_stat("scan", "videos", self.video_files)
            self.dash.update_stat("scan", "hashed", self.hash_done)
            self.dash.update_stat("scan", "phsig", self.phash_sigs)
            total_groups = self.groups_hash + self.groups_meta + self.groups_phash
            self.dash.update_stat("groups", "g_hash", self.groups_hash)
            self.dash.update_stat("groups", "g_meta", self.groups_meta)
            self.dash.update_stat("groups", "g_phash", self.groups_phash)
            self.dash.update_stat("groups", "g_total", total_groups)

    # ---- counters (thread-safe) ----
    def set_total_files(self, n: int):
        with self.lock:
            self.total_files = int(n)
        self.flush()

    def inc_scanned(self, n: int = 1, *, bytes_added: int = 0, is_video: bool = False):
        with self.lock:
            self.scanned_files += n
            self.bytes_seen += int(bytes_added)
            if is_video:
                self.video_files += n
        self.flush()

    def inc_hashed(self, n: int = 1):
        with self.lock:
            self.hash_done += n
        self.flush()

    def inc_phash_sig(self, n: int = 1):
        with self.lock:
            self.phash_sigs += n
        self.flush()

    def inc_group(self, mode: str, n: int = 1):
        with self.lock:
            if mode == "hash":
                self.groups_hash += n
            elif mode == "meta":
                self.groups_meta += n
            elif mode == "phash":
                self.groups_phash += n
        self.flush()

    def set_results(self, losers_count: int, bytes_total: int):
        if not self.enable_dash or not self.dash:
            return
        self.dash.update_stat("results", "losers", int(losers_count))
        self.dash.update_stat("results", "bytes", int(bytes_total))

# ----------------------------
# File enumeration
# ----------------------------

def _normalize_patterns(patts: Optional[List[str]]) -> Optional[List[str]]:
    if not patts:
        return None
    out = []
    for p in patts:
        p = (p or "").strip()
        if not p:
            continue
        # If user passed ".mp4" or "mp4", turn into "*.mp4"
        has_wild = any(ch in p for ch in "*?[")
        if not has_wild:
            ext = p.lstrip(".")
            p = f"*.{ext}"
        out.append(p)
    return out or None

def iter_files(
    root: Path,
    pattern: Optional[str] = None,
    max_depth: Optional[int] = None,
    *,
    patterns: Optional[List[str]] = None,
) -> Iterable[Path]:
    """
    Backward-compatible iterator.

    - Old style: iter_files(root, pattern="*.mp4", max_depth=None)
    - New style: iter_files(root, patterns=["*.mp4", "*.mkv"], max_depth=None)
    - Both can be used together; they'll be merged.
    """
    # Merge pattern + patterns
    merged: List[str] = []
    if patterns:
        merged.extend(patterns)
    if pattern:
        merged.append(pattern)
    norm = _normalize_patterns(merged)

    root = Path(root).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        if max_depth is not None:
            rel = Path(dirpath).resolve().relative_to(root)
            depth = 0 if str(rel) == "." else len(rel.parts)
            if depth > max_depth:
                dirnames[:] = []
                continue
        for name in filenames:
            if norm and not any(Path(name).match(p) for p in norm):
                continue
            yield Path(dirpath) / name

# ----------------------------
# Grouping
# ----------------------------

class Grouper:
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
        self._reporter: Optional[ProgressReporter] = None

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
                object.__setattr__(vm, "phash_signature", sig)  # frozen dataclass
                if self._reporter:
                    self._reporter.inc_phash_sig(1)
        return vm

    def collect(self, files: List[Path], reporter: Optional[ProgressReporter] = None) -> Dict[str, List[VideoMeta | FileMeta]]:
        """
        Returns groups keyed by an opaque ID; each group is a list of FileMeta/VideoMeta to consider duplicates.
        """
        self._reporter = reporter
        groups: Dict[str, List[VideoMeta | FileMeta]] = {}
        want_meta = self.mode in ("meta", "phash", "all")
        want_phash = self.mode in ("phash", "all")

        metas: List[VideoMeta | FileMeta] = []
        lock = threading.Lock()
        if self._reporter:
            self._reporter.set_total_files(len(files))

        def worker(p: Path):
            try:
                st = p.stat()
                bytes_added = int(st.st_size)
            except Exception:
                bytes_added = 0
            is_video = p.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"}
            if want_meta and is_video:
                m = self._collect_videometa(p, want_phash=want_phash)
            else:
                m = self._collect_filemeta(p)
            with lock:
                metas.append(m)
            if self._reporter:
                self._reporter.inc_scanned(1, bytes_added=bytes_added, is_video=is_video)

        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
            list(ex.map(worker, files))

        # Exact hash
        if self.mode in ("hash", "all"):
            by_hash: Dict[str, List[VideoMeta | FileMeta]] = defaultdict(list)

            def ensure_hash(m: VideoMeta | FileMeta):
                if m.sha256 is None:
                    h = sha256_file(m.path)
                    if h:
                        object.__setattr__(m, "sha256", h)
                if self._reporter:
                    self._reporter.inc_hashed(1)

            with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
                list(ex.map(ensure_hash, metas))

            for m in metas:
                if m.sha256:
                    by_hash[m.sha256].append(m)
            for h, lst in by_hash.items():
                if len(lst) > 1:
                    groups[f"hash:{h}"] = lst
                    if self._reporter:
                        self._reporter.inc_group("hash", 1)

        # Metadata (single union-find across all videos)
        if self.mode in ("meta", "all"):
            vids = [m for m in metas if isinstance(m, VideoMeta)]
            if vids:
                tol = max(0.0, float(self.duration_tolerance))
                bucket_size = max(1.0, tol)
                buckets: Dict[int, List[VideoMeta]] = defaultdict(list)
                for vm in vids:
                    dur = vm.duration if vm.duration is not None else -1.0
                    buckets[int(dur // bucket_size)].append(vm)

                parent = {id(v): id(v) for v in vids}

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

                for bkey in sorted(buckets.keys()):
                    curr = buckets[bkey]
                    nxt = buckets.get(bkey + 1, [])
                    # within bucket
                    for i in range(len(curr)):
                        for j in range(i + 1, len(curr)):
                            if similar(curr[i], curr[j]):
                                union(curr[i], curr[j])
                    # cross with next bucket
                    for a in curr:
                        for b in nxt:
                            if similar(a, b):
                                union(a, b)

                comps: Dict[int, List[VideoMeta]] = defaultdict(list)
                for v in vids:
                    comps[find(id(v))].append(v)
                gid = 0
                for comp in comps.values():
                    if len(comp) > 1:
                        groups[f"meta:{gid}"] = comp
                        gid += 1
                        if self._reporter:
                            self._reporter.inc_group("meta", 1)

        # Perceptual hashing
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
                    if self._reporter:
                        self._reporter.inc_group("phash", 1)

        # final flush before return
        if self._reporter:
            self._reporter.flush()
        return groups

# ----------------------------
# Keep policy / actions
# ----------------------------

def make_keep_key(order: Sequence[str]):
    def key(m: FileMeta | VideoMeta):
        duration = m.duration if isinstance(m, VideoMeta) and m.duration is not None else -1.0
        res = m.resolution_area if isinstance(m, VideoMeta) else 0
        vbr = m.video_bitrate if isinstance(m, VideoMeta) and m.video_bitrate else 0
        newer = m.mtime
        smaller = -m.size  # negative so "smaller" ranks higher in descending order
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
    keep_key = make_keep_key(keep_order)
    out = {}
    for gid, members in groups.items():
        sorted_members = sorted(members, key=lambda m: (keep_key(m), -len(m.path.as_posix())), reverse=True)
        out[gid] = (sorted_members[0], sorted_members[1:])
    return out

def ensure_backup_move(path: Path, backup_root: Path, base_root: Path) -> Path:
    # Preserve folder layout relative to base_root (auto-handles Windows paths)
    rel = path.resolve().relative_to(base_root.resolve())
    dest = backup_root.joinpath(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest

def delete_or_backup(losers: Iterable[FileMeta | VideoMeta], *, dry_run: bool, force: bool, backup_dir: Optional[Path], base_root: Path) -> Tuple[int, int]:
    count = 0
    total = 0
    for m in losers:
        size = m.size if isinstance(m.size, int) else 0
        if dry_run:
            _print(f"[cyan][DRY-RUN][/cyan] Would remove: {m.path}")
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
            _print(f"[green]Removed:[/] {m.path}" if console else f"Removed: {m.path}")
        except Exception as e:
            _print(f"[red]ERROR:[/] {m.path} -> {e}" if console else f"[ERROR] {m.path}: {e}")
    return count, total

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
        out[gid] = {"keep": str(keep.path), "losers": [str(l.path) for l in losers]}
        total_candidates += len(losers)
        total_size += sum(l.size for l in losers)
    payload = {"summary": {"groups": len(winners), "losers": total_candidates, "size_bytes": total_size}, "groups": out}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

# ----------------------------
# Apply report (new)
# ----------------------------

def apply_report(report_path: Path, *, dry_run: bool, force: bool, backup: Optional[Path], base_root: Optional[Path] = None) -> Tuple[int, int]:
    """
    Read a report JSON (from -R/--report) and delete/move all listed losers.
    Returns (count, total_bytes).
    """
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
        _print("Report contains no losers to process.")
        return (0, 0)

    # Derive base_root if not provided, so backup preserves structure sanely
    if base_root is None:
        try:
            # os.path.commonpath handles Windows/Posix uniformly for strings
            base_root = Path(os.path.commonpath([str(p) for p in loser_paths]))
        except Exception:
            base_root = Path("/")

    # Build synthetic FileMeta list with current sizes/mtimes
    metas: List[FileMeta] = []
    for p in loser_paths:
        try:
            st = p.stat()
            metas.append(FileMeta(path=p, size=st.st_size, mtime=st.st_mtime))
        except FileNotFoundError:
            # Skip missing files silently (already removed)
            continue
        except Exception:
            metas.append(FileMeta(path=p, size=0, mtime=0))

    if not metas:
        _print("All losers from report are missing; nothing to do.")
        return (0, 0)

    count = total = 0
    if dry_run:
        for m in metas:
            _print(f"[cyan][DRY-RUN][/cyan] Would remove: {m.path}")
            count += 1
            total += m.size
        return (count, total)

    # Real delete/move
    if backup:
        backup = backup.expanduser().resolve()
        backup.mkdir(parents=True, exist_ok=True)
    count, total = delete_or_backup(metas, dry_run=False, force=force, backup_dir=backup, base_root=base_root)
    return (count, total)

# ----------------------------
# CLI
# ----------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    epilog = r"""
Examples (PowerShell):

  # Exact duplicates (fast), dry-run, all files:
  python .\video_dedupe.py "D:\Pictures\Saved" -M hash -x

  # All modes, MP4 only, recurse fully, write report:
  python .\video_dedupe.py "D:\Pictures\Saved" -M all -p *.mp4 -r -x -R D:\report.json

  # Apply a previously generated report (delete/move losers listed in it):
  python .\video_dedupe.py --apply-report D:\report.json -f -b D:\Quarantine

  # Live dashboard:
  python .\video_dedupe.py "D:\Videos" -M all -p *.mp4 -r -x --live

  # Using --dir instead of positional, two patterns:
  python .\video_dedupe.py --dir "D:\Videos" -p *.mp4 -p *.mkv -M meta -u 3 -x

  # Preset high tolerance, back up losers:
  python .\video_dedupe.py "D:\Videos" --preset high -b D:\quarantine -f
"""
    p = argparse.ArgumentParser(
        description="Find and remove duplicate/similar videos & files, or apply a saved report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog
    )

    # Directory (positional or optional) — optional if --apply-report is used
    p.add_argument("directory", nargs="?", help="Root directory to scan")
    p.add_argument("-D", "--dir", "--directory", dest="dir_opt", help="Root directory (alternative to positional)")

    # Presets
    p.add_argument("--preset", choices=["low", "medium", "high"], help="Low/Medium/High tolerance presets")

    # Mode
    p.add_argument("-M", "--mode", choices=["hash", "meta", "phash", "all"], default="hash",
                   help="Duplicate detection mode (default: hash)")

    # Patterns (repeatable). Accepts '*.mp4' or '.mp4' or 'mp4'
    p.add_argument("-p", "--pattern", action="append",
                   help="Glob pattern to include (repeatable). Example: -p *.mp4 -p *.mkv")

    # Recursion
    p.add_argument("-r", "--recursive", nargs="?", const=-1, type=int,
                   help="Recurse: omit for none; -r for unlimited; -r N for depth N")

    # Metadata rules
    p.add_argument("--duration_tolerance", "-u", type=float, default=2.0,
                   help="Duration tolerance in seconds (default: 2.0)")
    p.add_argument("--same_res", action="store_true", help="Require same resolution")
    p.add_argument("--same_codec", action="store_true", help="Require same video codec")
    p.add_argument("--same_container", action="store_true", help="Require same container/format")

    # Perceptual hashing
    p.add_argument("--phash_frames", "-F", type=int, default=5, help="Frames to sample for phash (default: 5)")
    p.add_argument("--phash_threshold", "-T", type=int, default=12,
                   help="Per-frame Hamming distance threshold (64-bit, default: 12)")

    # Keep policy
    p.add_argument("--keep", "-k", type=str,
                   default="longer,resolution,video_bitrate,newer,smaller,deeper",
                   help="Order to keep best copy (comma list). Default: longer,resolution,video_bitrate,newer,smaller,deeper")

    # Actions & outputs
    p.add_argument("-x", "--dry-run", action="store_true", help="No changes; just print")
    p.add_argument("-f", "--force", action="store_true", help="Do not prompt for deletion")
    p.add_argument("-b", "--backup", type=str, help="Move losers to this folder instead of deleting")
    p.add_argument("-R", "--report", type=str, help="Write JSON report to this path")
    p.add_argument("-A", "--apply-report", type=str, help="Read a JSON report and delete/move all listed losers")

    # Live dashboard
    p.add_argument("--live", action="store_true", help="Show live, in-place progress with TermDash")
    p.add_argument("--refresh-rate", type=float, default=0.2, help="Dashboard refresh rate in seconds (default: 0.2)")

    return p.parse_args(argv)

def _apply_preset(args: argparse.Namespace):
    """
    Apply --preset defaults unless the user already overrode them.
    'low'    -> exact hashes only (strict)
    'medium' -> metadata duration match, same resolution, moderate tolerance
    'high'   -> all modes + phash, lenient tolerance
    """
    if not args.preset:
        return

    def if_default(curr, default, new):
        return new if curr == default else curr

    if args.preset == "low":
        args.mode = "hash"

    elif args.preset == "medium":
        args.mode = if_default(args.mode, "hash", "meta")
        args.duration_tolerance = if_default(args.duration_tolerance, 2.0, 3.0)
        args.same_res = True if not args.same_res else args.same_res

    elif args.preset == "high":
        args.mode = "all"
        if args.duration_tolerance == 2.0:
            args.duration_tolerance = 8.0
        if args.phash_frames == 5:
            args.phash_frames = 7
        if args.phash_threshold == 12:
            args.phash_threshold = 14

def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    # If applying a report, we don't need a scan directory.
    if args.apply_report:
        report_path = Path(args.apply_report).expanduser().resolve()
        if not report_path.exists():
            print(f"video_dedupe.py: error: report not found: {report_path}", file=sys.stderr)
            return 2
        base_root: Optional[Path] = None
        # If user passed a directory, use it as base for backup path preservation
        if args.directory or args.dir_opt:
            base_root = Path(args.directory or args.dir_opt).expanduser().resolve()
        backup = Path(args.backup).expanduser().resolve() if args.backup else None
        c, s = apply_report(report_path, dry_run=args.dry_run, force=args.force, backup=backup, base_root=base_root)
        _print(f"Report applied: removed/moved={c}; size={s/1_048_576:.2f} MiB")
        return 0

    # Accept positional or --dir for scanning mode
    root_str = args.directory or args.dir_opt
    if not root_str:
        print("video_dedupe.py: error: the following arguments are required: directory (positional) or --dir", file=sys.stderr)
        return 2
    root = Path(root_str).expanduser().resolve()
    if not root.exists():
        _print(f"[ERROR] Directory not found: {root}")
        return 2

    # Determine depth
    if args.recursive is None:
        max_depth: Optional[int] = 0
    elif args.recursive == -1:
        max_depth = None
    else:
        max_depth = max(0, int(args.recursive))

    # Normalize patterns
    patterns = _normalize_patterns(args.pattern)

    # Apply preset
    _apply_preset(args)

    # Prepare live reporter
    reporter = ProgressReporter(enable_dash=bool(args.live), refresh_rate=args.refresh_rate)
    reporter.start()

    try:
        files = list(iter_files(root, max_depth=max_depth, patterns=patterns))
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

        groups = g.collect(files, reporter=reporter)
        if not groups:
            _print("No duplicate groups found.")
            return 0

        keep_order = [t.strip() for t in args.keep.split(",") if t.strip()]
        winners = choose_winners(groups, keep_order)
        print_groups(groups, winners)

        if args.report:
            write_report(Path(args.report), winners)
            _print(f"Wrote report to: {args.report}")

        losers = [l for (_, ls) in winners.values() for l in ls]
        total_deleted = total_bytes = 0
        if losers:
            backup = Path(args.backup).expanduser().resolve() if args.backup else None
            c, s = delete_or_backup(losers, dry_run=args.dry_run, force=args.force, backup_dir=backup, base_root=root)
            total_deleted += c
            total_bytes += s

        # Final numbers to dashboard
        reporter.set_results(len(losers), sum(l.size for l in losers))
        _print(f"Candidates processed: {len(losers)}; removed/moved: {total_deleted}; size={total_bytes/1_048_576:.2f} MiB")
        return 0
    finally:
        reporter.stop()

if __name__ == "__main__":
    sys.exit(main())
