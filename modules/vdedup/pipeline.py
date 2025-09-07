#!/usr/bin/env python3
"""
vdedup.pipeline

Staged pipeline orchestrator with progress wiring.

Exports:
- PipelineConfig
- parse_pipeline(spec: str) -> list[int]
- run_pipeline(root, patterns, max_depth, selected_stages, cfg, cache=None, reporter=None)

Stages (select with -Q/--pipeline):
  1 = Q1 size-bucket (no hashing)
  2 = Q2 partial->full hashing (BLAKE3 slices, escalate to SHA-256 on collisions only)
  3 = Q3 ffprobe metadata clustering (duration/codec/container/resolution)
  4 = Q4 pHash visual similarity + optional subset detection

This module wires **all** heavy operations to ProgressReporter so the live UI
never looks idle while work is happening.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import hashlib
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

# Optional dependency (fast partial hashing)
try:
    import blake3  # type: ignore
    _BLAKE3_AVAILABLE = True
except Exception:
    _BLAKE3_AVAILABLE = False

# Local modules
try:
    from .models import FileMeta, VideoMeta
except Exception:
    # Fallback minimal stubs (in case of direct module execution)
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

# These are optional; Q3/Q4 will gracefully degrade if missing.
try:
    from .probe import probe_video  # -> VideoMeta
except Exception:
    probe_video = None  # type: ignore

try:
    from .phash import compute_phash_signature, alignable_distance  # type: ignore
except Exception:
    compute_phash_signature = None  # type: ignore
    alignable_distance = None  # type: ignore

try:
    from .progress import ProgressReporter  # only for type hints
except Exception:
    ProgressReporter = object  # type: ignore


# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------

def _is_video_suffix(p: Path) -> bool:
    return p.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"}

def _iter_files(root: Path, patterns: Optional[Sequence[str]], max_depth: Optional[int]) -> Iterator[Path]:
    """Yield files under root matching any of the provided glob patterns. Case-insensitive on Windows."""
    root = Path(root).resolve()
    patterns = list(patterns or [])
    if not patterns:
        # all files
        for dp, dn, fn in os.walk(root):
            if max_depth is not None:
                rel = Path(dp).resolve().relative_to(root)
                depth = 0 if str(rel) == "." else len(rel.parts)
                if depth > max_depth:
                    dn[:] = []
                    continue
            for name in fn:
                yield Path(dp) / name
        return

    # Normalise patterns: accept "mp4" or ".mp4" or "*.mp4"
    norm: List[str] = []
    for pat in patterns:
        s = (pat or "").strip()
        if not s:
            continue
        if not any(ch in s for ch in "*?["):
            s = f"*.{s.lstrip('.')}"
        norm.append(s)

    # On Windows, match case-insensitively by lowering names
    ci = sys.platform.startswith("win")

    for dp, dn, fn in os.walk(root):
        if max_depth is not None:
            rel = Path(dp).resolve().relative_to(root)
            depth = 0 if str(rel) == "." else len(rel.parts)
            if depth > max_depth:
                dn[:] = []
                continue
        for name in fn:
            to_match = name.lower() if ci else name
            if any(Path(to_match).match(p.lower() if ci else p) for p in norm):
                yield Path(dp) / name


def _sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def _blake3_partial_hex(path: Path, head: int = 1 << 20, tail: int = 1 << 20, mid: int = 0) -> str:
    """
    Hash up to head + mid + tail bytes (concatenated) using BLAKE3 for speed.
    Reads are bounded; safe on HDDs.
    """
    # If blake3 is missing, fall back to sha256 on the same slices (still bounded I/O).
    def _hinit():
        if _BLAKE3_AVAILABLE:
            return blake3.blake3()
        return hashlib.sha256()

    h = _hinit()
    sz = path.stat().st_size
    with path.open("rb", buffering=0) as f:
        if head > 0:
            f.seek(0)
            h.update(f.read(min(head, sz)))
        if mid > 0 and sz > (head + tail + mid):
            # sample from middle
            start = max(0, (sz // 2) - (mid // 2))
            f.seek(start)
            h.update(f.read(min(mid, sz - start)))
        if tail > 0 and sz > tail:
            start = max(0, sz - tail)
            f.seek(start)
            h.update(f.read(min(tail, sz - start)))
    return h.hexdigest()


# -------------------------------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class PipelineConfig:
    threads: int = 8
    # metadata grouping
    duration_tolerance: float = 2.0
    same_res: bool = False
    same_codec: bool = False
    same_container: bool = False
    # phash
    phash_frames: int = 5
    phash_threshold: int = 12
    # subset
    subset_detect: bool = False
    subset_min_ratio: float = 0.30
    subset_frame_threshold: int = 14
    # gpu hint for pHash
    gpu: bool = False


def parse_pipeline(spec: str) -> List[int]:
    """
    Parse strings like: "1-2", "1,3-4", "4"
    Returns sorted unique stage integers.
    """
    if not spec:
        return [1, 2]
    parts = [p.strip() for p in str(spec).split(",") if p.strip()]
    out: set[int] = set()
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            try:
                a_i, b_i = int(a), int(b)
                if a_i > b_i:
                    a_i, b_i = b_i, a_i
                for x in range(a_i, b_i + 1):
                    if 1 <= x <= 4:
                        out.add(x)
            except ValueError:
                continue
        else:
            try:
                x = int(p)
                if 1 <= x <= 4:
                    out.add(x)
            except ValueError:
                continue
    return sorted(out) or [1, 2]


# -------------------------------------------------------------------------------------------------
# Core pipeline
# -------------------------------------------------------------------------------------------------

Meta = Union[FileMeta, VideoMeta]
GroupMap = Dict[str, List[Meta]]

def _collect_filemeta(p: Path) -> FileMeta:
    st = p.stat()
    return FileMeta(path=p, size=int(st.st_size), mtime=float(st.st_mtime))

def _safe_cache_get(cache, path: Path, size: int, mtime: float) -> Optional[str]:
    """
    Try several common cache APIs to retrieve a sha256 for (path,size,mtime).
    Returns hex digest or None.
    """
    try:
        if cache is None:
            return None
        # Newer API?
        if hasattr(cache, "get"):
            return cache.get(path, size, mtime)  # type: ignore[attr-defined]
        if hasattr(cache, "get_sha"):
            return cache.get_sha(path, size, mtime)  # type: ignore[attr-defined]
    except Exception:
        return None
    return None

def _safe_cache_put(cache, path: Path, size: int, mtime: float, sha256: str) -> None:
    try:
        if cache is None:
            return
        if hasattr(cache, "put"):
            cache.put(path, size, mtime, sha256)  # type: ignore[attr-defined]
            return
        if hasattr(cache, "put_sha"):
            cache.put_sha(path, size, mtime, sha256)  # type: ignore[attr-defined]
            return
    except Exception:
        pass


def run_pipeline(
    root: Path,
    *,
    patterns: Optional[Sequence[str]],
    max_depth: Optional[int],
    selected_stages: Sequence[int],
    cfg: PipelineConfig,
    cache=None,
    reporter: Optional[ProgressReporter] = None,
) -> GroupMap:
    """
    Execute the selected stages and return a mapping of {group_id: [members]}.
    This function is **fully wired** to the ProgressReporter:
      - shows 'scanning' while enumerating/stat()ing files
      - shows Q2 partial / Q2 sha256 with live counters
      - updates group/results counters
    """
    root = Path(root).expanduser().resolve()
    # -----------------------------
    # Stage: scanning / enumeration
    # -----------------------------
    if reporter:
        reporter.start_stage("scanning", total=1)  # unknown total until we collect

    files: List[Path] = list(_iter_files(root, patterns, max_depth))
    if reporter:
        reporter.set_total_files(len(files))
        reporter.flush()

    # Build FileMeta list and size index; bump "scanned" while we stat().
    metas: List[FileMeta] = []
    by_size: Dict[int, List[FileMeta]] = defaultdict(list)

    for p in files:
        try:
            st = p.stat()
            fm = FileMeta(path=p, size=int(st.st_size), mtime=float(st.st_mtime))
            metas.append(fm)
            by_size[fm.size].append(fm)
            if reporter:
                reporter.inc_scanned(1, bytes_added=fm.size, is_video=_is_video_suffix(p))
        except FileNotFoundError:
            continue

    # This completes the 'scanning' placeholder
    if reporter:
        reporter.flush()

    groups: GroupMap = {}

    # -------------------------------------------
    # Q1: size buckets (cheap; no hashing needed)
    # -------------------------------------------
    if 1 in selected_stages:
        # We don't start a dedicated stage here (the heavy part was scanning).
        # But we can account groups formed by size alone if you want a "candidate" view.
        pass  # kept as lightweight step

    # -------------------------------------------------------
    # Q2: partial (blake3 slices) -> full sha256 on collisions
    # -------------------------------------------------------
    if 2 in selected_stages:
        # Candidates for partial hashing are the sizes with more than one file
        partial_candidates: List[FileMeta] = [m for lst in by_size.values() if len(lst) > 1 for m in lst]

        if reporter:
            reporter.start_stage("Q2 partial", total=len(partial_candidates))
            reporter.set_hash_total(len(partial_candidates))

        # Compute partial signatures
        partial_map: Dict[str, List[FileMeta]] = defaultdict(list)

        def _do_partial(m: FileMeta) -> Tuple[FileMeta, str]:
            sig = _blake3_partial_hex(m.path, head=1 << 20, tail=1 << 20, mid=0)
            if reporter:
                reporter.inc_hashed(1, cache_hit=False)
            return m, sig

        if partial_candidates:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for m, sig in ex.map(_do_partial, partial_candidates):
                    partial_map[sig].append(m)

        # Now escalate only those partial buckets that still collide
        to_full: List[FileMeta] = [m for lst in partial_map.values() if len(lst) > 1 for m in lst]

        if reporter:
            reporter.start_stage("Q2 sha256", total=len(to_full))
            reporter.set_hash_total(len(to_full))

        by_hash: Dict[str, List[FileMeta]] = defaultdict(list)

        def _do_full(m: FileMeta) -> Tuple[FileMeta, Optional[str], bool]:
            # Try cache first
            sha = _safe_cache_get(cache, m.path, m.size, m.mtime)
            if sha:
                if reporter:
                    reporter.inc_hashed(1, cache_hit=True)
                return m, sha, True
            try:
                sha = _sha256_file(m.path)
                if sha:
                    _safe_cache_put(cache, m.path, m.size, m.mtime, sha)
                if reporter:
                    reporter.inc_hashed(1, cache_hit=False)
                return m, sha, False
            except FileNotFoundError:
                if reporter:
                    reporter.inc_hashed(1, cache_hit=False)
                return m, None, False

        if to_full:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for (m, sha, _hit) in ex.map(_do_full, to_full):
                    if sha:
                        by_hash[sha].append(m)

        # Form groups from exact hashes
        formed = 0
        for h, lst in by_hash.items():
            if len(lst) > 1:
                groups[f"hash:{h}"] = lst
                formed += 1
        if reporter and formed:
            reporter.inc_group("hash", formed)
            reporter.flush()

    # ---------------------------------------------
    # Q3: ffprobe metadata (duration/format/codec…)
    # ---------------------------------------------
    if 3 in selected_stages:
        if probe_video is None:
            # Can't probe; skip stage gracefully
            pass
        else:
            # Only probe videos; to reduce cost, consider only sizes that are not already exact dupes
            vids: List[VideoMeta] = []

            if reporter:
                # We "probe" only once per file; set totals accordingly
                reporter.start_stage("Q3 metadata", total=len(metas))
                reporter.set_hash_total(len(metas))  # reuse hashed bar for "probed"

            def _probe_one(m: FileMeta) -> Optional[VideoMeta]:
                try:
                    vm = probe_video(m.path)
                    if reporter:
                        reporter.inc_hashed(1, cache_hit=False)
                    return vm
                except Exception:
                    if reporter:
                        reporter.inc_hashed(1, cache_hit=False)
                    return None

            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for vm in ex.map(_probe_one, metas):
                    if vm:
                        vids.append(vm)

            # Simple metadata-based grouping by duration buckets within tolerance
            tol = max(0.0, float(cfg.duration_tolerance))
            bucket: Dict[int, List[VideoMeta]] = defaultdict(list)
            for v in vids:
                d = v.duration if v.duration is not None else -1.0
                bucket[int(d // max(1.0, tol))].append(v)

            def _similar(a: VideoMeta, b: VideoMeta) -> bool:
                if a.duration is None or b.duration is None:
                    return False
                if abs(a.duration - b.duration) > tol:
                    return False
                if cfg.same_res and (a.width != b.width or a.height != b.height):
                    return False
                if cfg.same_codec and (a.vcodec != b.vcodec):
                    return False
                if cfg.same_container and (a.container != b.container):
                    return False
                return True

            # Union-find across each bucket and neighbor
            parent: Dict[int, int] = {}

            def _find(x: int) -> int:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def _union(a: int, b: int) -> None:
                ra, rb = _find(a), _find(b)
                if ra != rb:
                    parent[rb] = ra

            for v in vids:
                parent[id(v)] = id(v)

            keys = sorted(bucket.keys())
            for k in keys:
                curr = bucket[k]
                nxt = bucket.get(k + 1, [])
                for i in range(len(curr)):
                    for j in range(i + 1, len(curr)):
                        if _similar(curr[i], curr[j]):
                            _union(id(curr[i]), id(curr[j]))
                for a in curr:
                    for b in nxt:
                        if _similar(a, b):
                            _union(id(a), id(b))

            comps: Dict[int, List[VideoMeta]] = defaultdict(list)
            for v in vids:
                comps[_find(id(v))].append(v)

            formed = 0
            for idx, comp in comps.items():
                if len(comp) > 1:
                    groups[f"meta:{idx}"] = comp
                    formed += 1
            if reporter and formed:
                reporter.inc_group("meta", formed)
                reporter.flush()

    # ----------------------------------------------------------
    # Q4: pHash grouping & optional subset detection (expensive)
    # ----------------------------------------------------------
    if 4 in selected_stages and compute_phash_signature is not None:
        # Compute signatures
        # We will only do phash for videos we haven't conclusively grouped by hash already
        candidates: List[VideoMeta] = []
        for fm in metas:
            if _is_video_suffix(fm.path):
                # If we already grouped the file by exact hash, we can still include it for subset checks,
                # but it’s fine either way. We'll include all videos for simplicity.
                vm = probe_video(fm.path) if probe_video else VideoMeta(path=fm.path, size=fm.size, mtime=fm.mtime)
                candidates.append(vm)

        if reporter:
            reporter.start_stage("Q4 pHash", total=len(candidates))
            reporter.set_hash_total(len(candidates))

        def _do_phash(vm: VideoMeta) -> Optional[VideoMeta]:
            try:
                sig = compute_phash_signature(vm.path, frames=cfg.phash_frames, gpu=cfg.gpu)  # type: ignore[misc]
                if sig:
                    object.__setattr__(vm, "phash_signature", sig)
            finally:
                if reporter:
                    reporter.inc_hashed(1, cache_hit=False)
            return vm

        phashed: List[VideoMeta] = []
        if candidates:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for vm in ex.map(_do_phash, candidates):
                    if vm and vm.phash_signature:
                        phashed.append(vm)

        # Group by pHash proximity (simple threshold on aligned average distance)
        formed_phash = 0
        if phashed:
            used = set()
            gid = 0
            for i, a in enumerate(phashed):
                if i in used:
                    continue
                grp = [a]
                used.add(i)
                for j in range(i + 1, len(phashed)):
                    if j in used:
                        continue
                    b = phashed[j]
                    if not a.phash_signature or not b.phash_signature:
                        continue
                    if alignable_distance is None:
                        continue
                    best = alignable_distance(a.phash_signature, b.phash_signature, cfg.phash_threshold)  # type: ignore[misc]
                    if best is not None:
                        grp.append(b)
                        used.add(j)
                if len(grp) > 1:
                    groups[f"phash:{gid}"] = grp
                    gid += 1
                    formed_phash += 1
        if reporter and formed_phash:
            reporter.inc_group("phash", formed_phash)
            reporter.flush()

        # Optional subset detection (short version of longer one)
        if cfg.subset_detect and phashed and alignable_distance is not None:
            formed_subset = 0
            gid = 0
            # split into short/long pairs and test duration ratio + aligned distance
            vids_sorted = sorted([v for v in phashed if v.duration], key=lambda v: v.duration or 0.0)
            for si in range(len(vids_sorted)):
                for li in range(si + 1, len(vids_sorted)):
                    short, long = vids_sorted[si], vids_sorted[li]
                    if not short.duration or not long.duration:
                        continue
                    ratio = short.duration / (long.duration or 1.0)
                    if ratio < cfg.subset_min_ratio:
                        continue
                    best = alignable_distance(short.phash_signature, long.phash_signature, cfg.subset_frame_threshold)  # type: ignore[misc]
                    if best is not None:
                        groups[f"subset:{gid}"] = [short, long]
                        gid += 1
                        formed_subset += 1
            if reporter and formed_subset:
                # progress has no dedicated counter; reuse groups_subset if available
                try:
                    reporter.groups_subset += formed_subset  # type: ignore[attr-defined]
                    reporter.flush()
                except Exception:
                    pass

    # Final flush of results
    if reporter:
        # Summarize losers/bytes = 0 here; the CLI will compute precise counts after keep-policy
        reporter.set_results(dup_groups=len(groups), losers_count=0, bytes_total=0)
        reporter.flush()
    return groups
