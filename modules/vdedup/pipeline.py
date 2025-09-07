#!/usr/bin/env python3
"""
vdedup.pipeline

Staged pipeline orchestrator with progress wiring.

Exports:
- PipelineConfig
- parse_pipeline(spec: str) -> list[int]
- run_pipeline(root, patterns, max_depth, selected_stages, cfg, cache=None, reporter=None, skip_paths=None)

Stages (select with -Q/--pipeline):
  1 = Q1 size-bucket (no hashing)
  2 = Q2 partial->full hashing (BLAKE3 slices, escalate to SHA-256 on collisions only)
  3 = Q3 ffprobe metadata clustering (duration/codec/container/resolution)
  4 = Q4 pHash visual similarity + optional subset detection
  5 = accepted for convenience; currently a no-op (kept for future expansions)

This module wires **all** heavy operations to ProgressReporter so the live UI
never looks idle while work is happening.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union, Set

# Optional dependency (fast partial hashing)
try:
    import blake3  # type: ignore
    _BLAKE3_AVAILABLE = True
except Exception:
    _BLAKE3_AVAILABLE = False

# Local modules (absolute imports so CLI works installed or from source)
from vdedup.models import FileMeta, VideoMeta
from vdedup.progress import ProgressReporter
from vdedup.cache import HashCache


# -------------------------------------------------------------------------------------------------
# Config & parsing
# -------------------------------------------------------------------------------------------------

@dataclass
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
    # subset (sliding alignment)
    subset_detect: bool = False
    subset_min_ratio: float = 0.30
    subset_frame_threshold: int = 14
    # gpu hint for pHash
    gpu: bool = False


def parse_pipeline(spec: Optional[str]) -> List[int]:
    """
    Parse strings like: "1-2", "1,3-4", "4", "all".
    Empty/None -> [1,2,3,4] (full pipeline). We also accept up to 5; 5 is a no-op for convenience.
    """
    if not spec:
        return [1, 2, 3, 4]
    s = spec.strip().lower()
    if s in {"all", "full", "1-4", "1-5"}:
        return [1, 2, 3, 4]
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out: set[int] = set()
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            try:
                a_i, b_i = int(a), int(b)
                if a_i > b_i:
                    a_i, b_i = b_i, a_i
                # allow 5 but coerce to max 4 for now
                for x in range(max(1, a_i), min(5, b_i) + 1):
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
    r = sorted(out)
    return r or [1, 2, 3, 4]


# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------

_VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"}


def _is_video_suffix(p: Path) -> bool:
    return p.suffix.lower() in _VIDEO_EXT


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

    # Patterns are normalized by CLI; still accept "mp4" or ".mp4" or "*.mp4"
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


def _alignable_distance(a_sig, b_sig, per_frame_thresh: int) -> Optional[float]:
    """
    Sliding alignment (subset) average Hamming distance. None if not alignable under threshold.
    """
    if not a_sig or not b_sig:
        return None
    A, B = (a_sig, b_sig) if len(a_sig) <= len(b_sig) else (b_sig, a_sig)
    best = None
    for offset in range(0, len(B) - len(A) + 1):
        dist = 0
        for i in range(len(A)):
            x = int(A[i]) ^ int(B[i + offset])
            dist += x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
        avg = dist / len(A)
        if best is None or avg < best:
            best = avg
    return best if (best is not None and best <= per_frame_thresh) else None


# -------------------------------------------------------------------------------------------------
# Main pipeline
# -------------------------------------------------------------------------------------------------

Meta = Union[FileMeta, VideoMeta]
GroupMap = Dict[str, List[Meta]]


def run_pipeline(
    root: Path,
    *,
    patterns: Optional[Sequence[str]],
    max_depth: Optional[int],
    selected_stages: Sequence[int],
    cfg: PipelineConfig,
    cache: Optional[HashCache] = None,
    reporter: Optional[ProgressReporter] = None,
    skip_paths: Optional[Set[Path]] = None,
) -> GroupMap:
    """
    Execute the selected stages and return a mapping of {group_id: [members]}.
    Progressive exclusion is applied:
      - Q1 just determines candidates for Q2.
      - Q2 exact-hash groups are EXCLUDED from Q3/Q4 (fastest-first).
      - Q3 metadata groups are EXCLUDED from Q4.
    skip_paths: if provided, any file in this set is ignored during scanning.
    """
    root = Path(root).expanduser().resolve()
    reporter = reporter or ProgressReporter(enable_dash=False)

    # -----------------------------
    # Stage: scanning / enumeration
    # -----------------------------
    files: List[Path] = list(_iter_files(root, patterns, max_depth))

    # Apply excludes early
    if skip_paths:
        skip_norm = {p.expanduser().resolve() for p in skip_paths}
        files = [f for f in files if f.expanduser().resolve() not in skip_norm]

    reporter.set_total_files(len(files))
    reporter.start_stage("scanning", total=len(files))

    metas: List[FileMeta] = []
    by_size: Dict[int, List[FileMeta]] = defaultdict(list)

    def scan_one(p: Path) -> None:
        reporter.wait_if_paused()
        if reporter.should_quit():
            return
        try:
            st = p.stat()
            fm = FileMeta(path=p, size=int(st.st_size), mtime=float(st.st_mtime))
        except Exception:
            fm = FileMeta(path=p, size=0, mtime=0.0)
        metas.append(fm)
        by_size[fm.size].append(fm)
        reporter.inc_scanned(1, bytes_added=fm.size, is_video=_is_video_suffix(p))

    if files:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
            list(ex.map(scan_one, files))

    if reporter.should_quit():
        reporter.flush()
        return {}

    # -------------------------------------------
    # Q1: size buckets (cheap; no hashing needed)
    # -------------------------------------------
    size_collisions: List[FileMeta] = []
    if 1 in selected_stages:
        for bucket in by_size.values():
            if len(bucket) > 1:
                size_collisions.extend(bucket)

    groups: GroupMap = {}
    excluded_after_q2: Set[Path] = set()
    excluded_after_q3: Set[Path] = set()

    # -------------------------------------------------------
    # Q2: partial (blake3 slices) -> full sha256 on collisions
    # -------------------------------------------------------
    if 2 in selected_stages and size_collisions:
        reporter.start_stage("Q2 partial", total=len(size_collisions))
        reporter.set_hash_total(len(size_collisions))

        partial_map: Dict[str, List[FileMeta]] = defaultdict(list)

        def _do_partial(m: FileMeta) -> Tuple[FileMeta, str]:
            reporter.wait_if_paused()
            if reporter.should_quit():
                return (m, f"__quit__{id(m)}")
            sig = _blake3_partial_hex(m.path, head=1 << 20, tail=1 << 20, mid=0)
            reporter.inc_hashed(1, cache_hit=False)
            return m, sig

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
            for m, sig in ex.map(_do_partial, size_collisions):
                if sig.startswith("__quit__"):
                    continue
                partial_map[sig].append(m)

        if reporter.should_quit():
            reporter.flush();
            return groups

        # Escalate only partial buckets that still collide
        to_full: List[FileMeta] = [m for lst in partial_map.values() if len(lst) > 1 for m in lst]

        reporter.start_stage("Q2 sha256", total=len(to_full))
        reporter.set_hash_total(len(to_full))

        by_hash: Dict[str, List[FileMeta]] = defaultdict(list)

        def _do_full(m: FileMeta) -> Tuple[FileMeta, Optional[str], bool]:
            reporter.wait_if_paused()
            if reporter.should_quit():
                return (m, None, False)
            # Try cache first
            sha = None
            try:
                if cache:
                    sha = cache.get_sha256(m.path, m.size, m.mtime)  # type: ignore[attr-defined]
            except Exception:
                sha = None
            if sha:
                reporter.inc_hashed(1, cache_hit=True)
                return m, sha, True
            try:
                sha = _sha256_file(m.path)
                if sha and cache:
                    try:
                        cache.put_field(m.path, m.size, m.mtime, "sha256", sha)
                    except Exception:
                        pass
                reporter.inc_hashed(1, cache_hit=False)
                return m, sha, False
            except Exception:
                reporter.inc_hashed(1, cache_hit=False)
                return m, None, False

        if to_full:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for (m, sha, _hit) in ex.map(_do_full, to_full):
                    if sha:
                        by_hash[sha].append(m)

        # Form groups from exact hashes and mark **all members** excluded for later stages
        formed = 0
        for h, lst in by_hash.items():
            if len(lst) > 1:
                groups[f"hash:{h}"] = lst
                for fm in lst:
                    excluded_after_q2.add(fm.path.expanduser().resolve())
                formed += 1
        if formed:
            reporter.inc_group("hash", formed)
            reporter.flush()

    if reporter.should_quit():
        reporter.flush()
        return groups

    # ---------------------------------------------
    # Q3: ffprobe metadata (duration/format/codec…)
    # ---------------------------------------------
    if 3 in selected_stages:
        # Keep only videos not excluded by Q2
        vids_in: List[VideoMeta] = [
            VideoMeta(path=m.path, size=m.size, mtime=m.mtime)
            for m in metas
            if _is_video_suffix(m.path) and (m.path.expanduser().resolve() not in excluded_after_q2)
        ]

        if vids_in:
            reporter.start_stage("Q3 metadata", total=len(vids_in))
            reporter.set_hash_total(len(vids_in))  # reuse hashed bar for "probed"

            # Lazy import to avoid hard dependency during tests
            try:
                from vdedup import probe as _probe_mod  # type: ignore
            except Exception:
                _probe_mod = None  # type: ignore

            def _probe_video(path: Path) -> Optional[VideoMeta]:
                if _probe_mod is None:
                    return None
                if hasattr(_probe_mod, "probe_video"):
                    return _probe_mod.probe_video(path)  # type: ignore[attr-defined]
                if hasattr(_probe_mod, "run_ffprobe_json"):
                    fmt = _probe_mod.run_ffprobe_json(path)  # type: ignore[attr-defined]
                    if not fmt:
                        return None
                    try:
                        duration = float(fmt.get("format", {}).get("duration", 0.0))
                    except Exception:
                        duration = None
                    width = height = None
                    try:
                        for s in fmt.get("streams", []):
                            if s.get("codec_type") == "video":
                                width = int(s.get("width") or 0) or None
                                height = int(s.get("height") or 0) or None
                                break
                    except Exception:
                        pass
                    st = path.stat()
                    return VideoMeta(path=path, size=st.st_size, mtime=st.st_mtime, duration=duration, width=width, height=height)
                return None

            def _probe_one(vm: VideoMeta) -> Optional[VideoMeta]:
                reporter.wait_if_paused()
                if reporter.should_quit():
                    return None
                out = _probe_video(vm.path)
                reporter.inc_hashed(1, cache_hit=False)
                return out if out else None

            probed: List[VideoMeta] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for vm in ex.map(_probe_one, vids_in):
                    if vm:
                        probed.append(vm)

            # Cluster by duration buckets within tolerance (+ optional constraints)
            tol = max(0.0, float(cfg.duration_tolerance))
            bucket: Dict[int, List[VideoMeta]] = defaultdict(list)
            for v in probed:
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

            for v in probed:
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
            for v in probed:
                comps[_find(id(v))].append(v)

            formed = 0
            gid = 0
            for comp in comps.values():
                if len(comp) > 1:
                    groups[f"meta:{gid}"] = comp
                    for vm in comp:
                        excluded_after_q3.add(vm.path.expanduser().resolve())
                    gid += 1
                    formed += 1
            if formed:
                reporter.inc_group("meta", formed)
                reporter.flush()

            video_for_q4 = probed
        else:
            video_for_q4 = []
    else:
        # Q3 not selected — allow Q4 on all videos not excluded by Q2
        video_for_q4 = [
            VideoMeta(path=m.path, size=m.size, mtime=m.mtime)
            for m in metas
            if _is_video_suffix(m.path) and (m.path.expanduser().resolve() not in excluded_after_q2)
        ]

    if reporter.should_quit():
        reporter.flush()
        return groups

    # ----------------------------------------------------------
    # Q4: pHash grouping & optional subset detection (expensive)
    # ----------------------------------------------------------
    if 4 in selected_stages and video_for_q4:
        # Exclude videos already grouped by Q3
        pending_for_q4 = [v for v in video_for_q4 if v.path.expanduser().resolve() not in excluded_after_q3]

        # Lazy import phash helpers here (avoid import-time errors in minimal env/tests)
        try:
            from vdedup.phash import compute_phash_signature, phash_distance  # type: ignore
        except Exception:
            compute_phash_signature = None  # type: ignore
            phash_distance = None  # type: ignore

        if compute_phash_signature and phash_distance and pending_for_q4:
            reporter.start_stage("Q4 pHash", total=len(pending_for_q4))
            reporter.set_hash_total(len(pending_for_q4))

            def _do_phash(vm: VideoMeta) -> VideoMeta:
                reporter.wait_if_paused()
                if reporter.should_quit():
                    return vm
                sig = compute_phash_signature(vm.path, frames=cfg.phash_frames, gpu=cfg.gpu)
                if sig:
                    vm = VideoMeta(
                        path=vm.path, size=vm.size, mtime=vm.mtime,
                        duration=vm.duration, width=vm.width, height=vm.height,
                        container=vm.container, vcodec=vm.vcodec, acodec=vm.acodec,
                        overall_bitrate=vm.overall_bitrate, video_bitrate=vm.video_bitrate,
                        phash_signature=tuple(int(x) for x in sig),
                    )
                reporter.inc_hashed(1, cache_hit=False)
                return vm

            phashed: List[VideoMeta] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for vm in ex.map(_do_phash, pending_for_q4):
                    phashed.append(vm)

            # Group by pHash proximity (same-length matches)
            formed_phash = 0
            if phashed:
                used = set()
                gid = 0
                for i, a in enumerate(phashed):
                    if not a.phash_signature:
                        continue
                    if i in used:
                        continue
                    grp = [a]
                    used.add(i)
                    for j in range(i + 1, len(phashed)):
                        if j in used:
                            continue
                        b = phashed[j]
                        if not b.phash_signature:
                            continue
                        L = min(len(a.phash_signature), len(b.phash_signature))
                        if L < 2:
                            continue
                        dist = phash_distance(a.phash_signature[:L], b.phash_signature[:L])  # type: ignore[misc]
                        if dist <= cfg.phash_threshold * L:
                            grp.append(b)
                            used.add(j)
                    if len(grp) > 1:
                        groups[f"phash:{gid}"] = grp
                        gid += 1
                        formed_phash += 1
            if formed_phash:
                reporter.inc_group("phash", formed_phash)
                reporter.flush()

            # Optional subset detection (short version of longer one)
            if cfg.subset_detect and phashed:
                formed_subset = 0
                gid = 0
                vids_sorted = sorted([v for v in phashed if v.duration], key=lambda v: v.duration or 0.0)
                for si in range(len(vids_sorted)):
                    for li in range(si + 1, len(vids_sorted)):
                        short, long = vids_sorted[si], vids_sorted[li]
                        if not short.duration or not long.duration:
                            continue
                        ratio = short.duration / (long.duration or 1.0)
                        if ratio < cfg.subset_min_ratio:
                            continue
                        best = _alignable_distance(short.phash_signature, long.phash_signature, cfg.subset_frame_threshold)  # type: ignore[arg-type]
                        if best is not None:
                            groups[f"subset:{gid}"] = [short, long]
                            gid += 1
                            formed_subset += 1
                if formed_subset:
                    reporter.groups_subset += formed_subset  # surface in UI
                    reporter.flush()

    # Final flush of results (CLI will compute losers/bytes after keep-policy)
    reporter.set_results(dup_groups=len(groups), losers_count=0, bytes_total=0)
    reporter.flush()
    return groups
