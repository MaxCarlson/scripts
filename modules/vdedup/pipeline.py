#!/usr/bin/env python3
from __future__ import annotations
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .models import FileMeta, VideoMeta
from .cache import HashCache
from .hashers import partial_hash, sha256_file
from .probe import run_ffprobe_json
from .phash import compute_phash_signature
from .grouping import group_by_same_size, choose_winners, alignable_avg_distance

Meta = Union[FileMeta, VideoMeta]

class PipelineConfig:
    def __init__(
        self,
        *,
        threads: int = 8,
        block_size: int = 1 << 20,
        duration_tolerance: float = 2.0,
        same_res: bool = False,
        same_codec: bool = False,
        same_container: bool = False,
        phash_frames: int = 5,
        phash_threshold: int = 12,
        subset_detect: bool = False,
        subset_min_ratio: float = 0.30,
        subset_frame_threshold: int = 18,
        gpu: bool = False,
        head_bytes: int = 2 * 1024 * 1024,
        tail_bytes: int = 2 * 1024 * 1024,
        mid_bytes: int = 0,
    ):
        self.threads = max(1, int(threads))
        self.block_size = max(64 * 1024, int(block_size))
        self.duration_tolerance = float(duration_tolerance)
        self.same_res = bool(same_res)
        self.same_codec = bool(same_codec)
        self.same_container = bool(same_container)
        self.phash_frames = int(phash_frames)
        self.phash_threshold = int(phash_threshold)
        self.subset_detect = bool(subset_detect)
        self.subset_min_ratio = float(subset_min_ratio)
        self.subset_frame_threshold = int(subset_frame_threshold)
        self.gpu = bool(gpu)
        self.head_bytes = int(head_bytes)
        self.tail_bytes = int(tail_bytes)
        self.mid_bytes = int(mid_bytes)


def parse_pipeline(p: str) -> List[int]:
    """
    Parse -Q/--pipeline like "1", "1-3", "1,3-4", "2,4".
    Valid stages: 1=by-size, 2=partial+sha256, 3=metadata, 4=phash(+subset)
    """
    if not p:
        return [1, 2, 3, 4]
    out: List[int] = []
    for tok in p.split(","):
        tok = tok.strip()
        if "-" in tok:
            a, b = tok.split("-", 1)
            try:
                a_i, b_i = int(a), int(b)
                for i in range(min(a_i, b_i), max(a_i, b_i) + 1):
                    if 1 <= i <= 4:
                        out.append(i)
            except Exception:
                continue
        else:
            try:
                i = int(tok)
                if 1 <= i <= 4:
                    out.append(i)
            except Exception:
                continue
    # de-dup while preserving order
    seen = set()
    final: List[int] = []
    for i in out or [1, 2, 3, 4]:
        if i not in seen:
            seen.add(i)
            final.append(i)
    return final


def iter_files(root: Path, patterns: Optional[List[str]], max_depth: Optional[int]) -> Iterable[Path]:
    root = root.resolve()
    normalized = None
    if patterns:
        normalized = []
        for p in patterns:
            p = (p or "").strip()
            if not p:
                continue
            if not any(ch in p for ch in "*?["):
                p = f"*.{p.lstrip('.')}"
            normalized.append(p)
    for dirpath, dirnames, filenames in os.walk(root):
        if max_depth is not None:
            rel = Path(dirpath).resolve().relative_to(root)
            depth = 0 if str(rel) == "." else len(rel.parts)
            if depth > max_depth:
                dirnames[:] = []
                continue
        for name in filenames:
            if normalized and not any(Path(name).match(p) for p in normalized):
                continue
            yield Path(dirpath) / name


def collect_basic_meta(paths: Iterable[Path], *, cache: Optional[HashCache]) -> List[Meta]:
    metas: List[Meta] = []
    for p in paths:
        try:
            st = p.stat()
        except Exception:
            continue
        # treat common video extensions as VideoMeta, everything else as FileMeta
        is_video = p.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"}
        if is_video:
            vm = VideoMeta(path=p, size=st.st_size, mtime=st.st_mtime)
            # fast path: cached ffprobe?
            if cache:
                rec = cache.get_video_meta(p, st.st_size, st.st_mtime)
                if rec:
                    try:
                        vm = VideoMeta(
                            path=p, size=st.st_size, mtime=st.st_mtime,
                            duration=float(rec.get("duration")) if rec.get("duration") is not None else None,
                            width=int(rec.get("width")) if rec.get("width") is not None else None,
                            height=int(rec.get("height")) if rec.get("height") is not None else None,
                            container=rec.get("container"),
                            vcodec=rec.get("vcodec"),
                            acodec=rec.get("acodec"),
                            overall_bitrate=int(rec.get("overall_bitrate")) if rec.get("overall_bitrate") is not None else None,
                            video_bitrate=int(rec.get("video_bitrate")) if rec.get("video_bitrate") is not None else None,
                        )
                    except Exception:
                        pass
            metas.append(vm)
        else:
            metas.append(FileMeta(path=p, size=st.st_size, mtime=st.st_mtime))
    return metas


def stage1_by_size(metas: List[Meta]) -> Dict[str, List[Meta]]:
    files_only = [FileMeta(path=m.path, size=m.size, mtime=m.mtime) for m in metas]
    return {k: list(v) for k, v in group_by_same_size(files_only).items()}


def stage2_partial_and_sha(metas: List[Meta], cfg: PipelineConfig, cache: Optional[HashCache]) -> Dict[str, List[Meta]]:
    # Compute partial hashes for files that share size
    by_size: Dict[int, List[Meta]] = defaultdict(list)
    for m in metas:
        by_size[m.size].append(m)
    collisions: List[List[Meta]] = [lst for lst in by_size.values() if len(lst) > 1]
    out: Dict[str, List[Meta]] = {}
    gid = 0
    for group in collisions:
        # Partial pass
        buckets: Dict[Tuple[str, str, Optional[str], str], List[Meta]] = defaultdict(list)
        for m in group:
            rec = cache.get_partial(m.path, m.size, m.mtime) if cache else None
            if rec:
                head, tail, mid, algo = rec.get("head"), rec.get("tail"), rec.get("mid"), rec.get("algo", "blake3")
            else:
                ph = partial_hash(m.path, head_bytes=cfg.head_bytes, tail_bytes=cfg.tail_bytes, mid_bytes=cfg.mid_bytes)
                if not ph:
                    continue
                head, tail, mid, algo = ph
                if cache:
                    cache.put_field(m.path, m.size, m.mtime, "partial", {
                        "algo": algo, "head": head, "tail": tail, "mid": mid,
                        "head_bytes": cfg.head_bytes, "tail_bytes": cfg.tail_bytes, "mid_bytes": cfg.mid_bytes
                    })
            buckets[(head, tail, mid, algo)].append(m)

        # Within each partial bucket that still collides, compute full SHA-256
        for key, lst in buckets.items():
            if len(lst) <= 1:
                continue
            by_sha: Dict[str, List[Meta]] = defaultdict(list)
            for m in lst:
                cached = cache.get_sha256(m.path, m.size, m.mtime) if cache else None
                sha = cached or sha256_file(m.path, cfg.block_size)
                if sha and not cached and cache:
                    cache.put_field(m.path, m.size, m.mtime, "sha256", sha)
                if sha:
                    by_sha[sha].append(m)
            for h, members in by_sha.items():
                if len(members) > 1:
                    out[f"hash:{gid}"] = members
                    gid += 1
    return out


def stage3_metadata(metas: List[Meta], cfg: PipelineConfig, cache: Optional[HashCache]) -> Dict[str, List[VideoMeta]]:
    vids: List[VideoMeta] = [m if isinstance(m, VideoMeta) else VideoMeta(path=m.path, size=m.size, mtime=m.mtime) for m in metas]
    # Fill missing meta from cache or ffprobe
    for i, vm in enumerate(vids):
        if vm.duration is not None:
            continue
        rec = cache.get_video_meta(vm.path, vm.size, vm.mtime) if cache else None
        if rec:
            try:
                vids[i] = VideoMeta(
                    path=vm.path, size=vm.size, mtime=vm.mtime,
                    duration=float(rec.get("duration")) if rec.get("duration") is not None else None,
                    width=int(rec.get("width")) if rec.get("width") is not None else None,
                    height=int(rec.get("height")) if rec.get("height") is not None else None,
                    container=rec.get("container"), vcodec=rec.get("vcodec"), acodec=rec.get("acodec"),
                    overall_bitrate=int(rec.get("overall_bitrate")) if rec.get("overall_bitrate") is not None else None,
                    video_bitrate=int(rec.get("video_bitrate")) if rec.get("video_bitrate") is not None else None,
                )
                continue
            except Exception:
                pass
        fmt = run_ffprobe_json(vm.path)
        duration = width = height = vcodec = acodec = container = overall_bitrate = video_bitrate = None
        if fmt:
            f = fmt.get("format", {})
            try:
                duration = float(f.get("duration")) if f.get("duration") is not None else None
                container = f.get("format_name")
                if f.get("bit_rate") and str(f.get("bit_rate")).isdigit():
                    overall_bitrate = int(f.get("bit_rate"))
            except Exception:
                pass
            for s in fmt.get("streams", []):
                if s.get("codec_type") == "video" and vcodec is None:
                    vcodec = s.get("codec_name")
                    w, h = s.get("width"), s.get("height")
                    if isinstance(w, int) and isinstance(h, int):
                        width, height = w, h
                    br = s.get("bit_rate")
                    if isinstance(br, str) and br.isdigit():
                        video_bitrate = int(br)
                    elif isinstance(br, int):
                        video_bitrate = br
                elif s.get("codec_type") == "audio" and acodec is None:
                    acodec = s.get("codec_name")
        vm2 = VideoMeta(
            path=vm.path, size=vm.size, mtime=vm.mtime, duration=duration, width=width, height=height,
            container=container, vcodec=vcodec, acodec=acodec, overall_bitrate=overall_bitrate, video_bitrate=video_bitrate
        )
        vids[i] = vm2
        if cache:
            cache.put_field(vm2.path, vm2.size, vm2.mtime, "video_meta", {
                "duration": vm2.duration, "width": vm2.width, "height": vm2.height,
                "container": vm2.container, "vcodec": vm2.vcodec, "acodec": vm2.acodec,
                "overall_bitrate": vm2.overall_bitrate, "video_bitrate": vm2.video_bitrate
            })
    # Group videos by metadata
    tol = max(0.0, float(cfg.duration_tolerance))
    buckets: Dict[int, List[VideoMeta]] = defaultdict(list)
    for vm in vids:
        dur = vm.duration if vm.duration is not None else -1.0
        buckets[int((dur // max(1.0, tol)) if dur >= 0 else -1)].append(vm)
    groups: Dict[str, List[VideoMeta]] = {}
    gid = 0
    def similar(a: VideoMeta, b: VideoMeta) -> bool:
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
    for key in sorted(buckets.keys()):
        curr = buckets[key]
        nxt = buckets.get(key + 1, [])
        comp = []
        marked = [False] * len(curr)
        for i in range(len(curr)):
            if marked[i]:
                continue
            g = [curr[i]]
            for j in range(i + 1, len(curr)):
                if not marked[j] and similar(curr[i], curr[j]):
                    g.append(curr[j]); marked[j] = True
            for b in nxt:
                if similar(curr[i], b):
                    g.append(b)
            if len(g) > 1:
                groups[f"meta:{gid}"] = g; gid += 1
    return groups


def stage4_phash_subset(metas: List[Meta], cfg: PipelineConfig, cache: Optional[HashCache]) -> Dict[str, List[VideoMeta]]:
    vids: List[VideoMeta] = [m if isinstance(m, VideoMeta) else VideoMeta(path=m.path, size=m.size, mtime=m.mtime) for m in metas]
    # Load/compute phash signatures
    for i, vm in enumerate(vids):
        if vm.phash_signature:
            continue
        rec = cache.get_phash(vm.path, vm.size, vm.mtime) if cache else None
        if rec:
            try:
                vids[i] = VideoMeta(**{**dataclasses.asdict(vm), "phash_signature": tuple(int(x) for x in rec)})
                continue
            except Exception:
                pass
        sig = compute_phash_signature(vm.path, frames=cfg.phash_frames, gpu=cfg.gpu)
        if sig:
            vids[i] = VideoMeta(path=vm.path, size=vm.size, mtime=vm.mtime, duration=vm.duration, width=vm.width, height=vm.height,
                                container=vm.container, vcodec=vm.vcodec, acodec=vm.acodec,
                                overall_bitrate=vm.overall_bitrate, video_bitrate=vm.video_bitrate,
                                phash_signature=sig)
            if cache:
                cache.put_field(vm.path, vm.size, vm.mtime, "phash", list(map(int, sig)))

    # Group by phash distance (same length videos)
    groups: Dict[str, List[VideoMeta]] = {}
    gid = 0
    for i in range(len(vids)):
        a = vids[i]
        if not a.phash_signature:
            continue
        group = [a]
        for j in range(i + 1, len(vids)):
            b = vids[j]
            if not b.phash_signature:
                continue
            L = min(len(a.phash_signature), len(b.phash_signature))
            if L < 2:
                continue
            # Average per-frame distance threshold
            dist = 0
            for k in range(L):
                x = int(a.phash_signature[k]) ^ int(b.phash_signature[k])
                dist += x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
            avg = dist / L
            if avg <= cfg.phash_threshold:
                group.append(b)
        if len(group) > 1:
            groups[f"phash:{gid}"] = group
            gid += 1

    # Optional subset detection (short vs long)
    if cfg.subset_detect:
        subset_gid = gid
        for i in range(len(vids)):
            a = vids[i]
            if not a.phash_signature or not a.duration:
                continue
            for j in range(i + 1, len(vids)):
                b = vids[j]
                if not b.phash_signature or not b.duration:
                    continue
                short, long = (a, b) if a.duration <= b.duration else (b, a)
                ratio = (short.duration or 0.0) / (long.duration or 1.0)
                if ratio < cfg.subset_min_ratio:
                    continue
                best = alignable_avg_distance(short.phash_signature, long.phash_signature, cfg.subset_frame_threshold)
                if best is not None:
                    groups[f"subset:{subset_gid}"] = [short, long]
                    subset_gid += 1
    return groups


def run_pipeline(
    root: Path,
    patterns: Optional[List[str]],
    max_depth: Optional[int],
    selected_stages: Sequence[int],
    cfg: PipelineConfig,
    cache: Optional[HashCache],
) -> Dict[str, List[Meta]]:
    paths = list(iter_files(root, patterns, max_depth))
    metas = collect_basic_meta(paths, cache=cache)

    all_groups: Dict[str, List[Meta]] = {}
    if 1 in selected_stages:
        all_groups.update(stage1_by_size(metas))
    if 2 in selected_stages:
        all_groups.update(stage2_partial_and_sha(metas, cfg, cache))
    if 3 in selected_stages:
        all_groups.update(stage3_metadata(metas, cfg, cache))
    if 4 in selected_stages:
        all_groups.update(stage4_phash_subset(metas, cfg, cache))
    return all_groups
