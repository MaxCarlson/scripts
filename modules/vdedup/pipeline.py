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
  6 = Q6 audio fingerprinting and analysis (audio similarity beyond metadata)
  7 = Q7 advanced content analysis (scene detection, motion vectors, keyframes)

This module wires **all** heavy operations to ProgressReporter so the live UI
never looks idle while work is happening.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
import sys
import threading
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
    subset_min_ratio: float = 0.10  # Aligned with research: ≥10% overlap threshold
    subset_frame_threshold: int = 14
    # gpu hint for pHash
    gpu: bool = False
    # artifact handling
    include_partials: bool = False


def parse_pipeline(spec: Optional[str]) -> List[int]:
    """
    Parse strings like: "1-2", "1,3-4", "4", "all".
    Empty/None -> [1,2,3,4] (full pipeline). Now supports up to stage 7.
    """
    if not spec:
        return [1, 2, 3, 4]
    s = spec.strip().lower()
    if s in {"all", "full"}:
        return [1, 2, 3, 4, 5, 6, 7]  # Full pipeline with all stages
    if s in {"1-4", "1-5"}:
        return [1, 2, 3, 4]  # Legacy compatibility
    if s in {"1-6"}:
        return [1, 2, 3, 4, 5, 6]
    if s in {"1-7"}:
        return [1, 2, 3, 4, 5, 6, 7]
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out: set[int] = set()
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            try:
                a_i, b_i = int(a), int(b)
                if a_i > b_i:
                    a_i, b_i = b_i, a_i
                # Now allow up to stage 7
                for x in range(max(1, a_i), min(8, b_i) + 1):
                    if 1 <= x <= 7:
                        out.add(x)
            except ValueError:
                continue
        else:
            try:
                x = int(p)
                if 1 <= x <= 7:
                    out.add(x)
            except ValueError:
                continue
    r = sorted(out)
    return r or [1, 2, 3, 4]


def _build_stage_plan(selected_stages: Sequence[int]) -> List[str]:
    plan: List[str] = ["discovering files", "scanning files"]
    if 1 in selected_stages:
        plan.append("Q1 size bucketing")
    if 2 in selected_stages:
        plan.extend(["Q2 partial", "Q2 full hash"])
    if 3 in selected_stages:
        plan.append("Q3 metadata")
    if 4 in selected_stages:
        plan.append("Q4 pHash")
    if 5 in selected_stages:
        plan.append("Q5 scene")
    if 6 in selected_stages:
        plan.append("Q6 audio")
    if 7 in selected_stages:
        plan.append("Q7 timeline")
    return plan


# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------

_VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"}
_ARTIFACT_SUFFIXES = (
    ".part",
    ".partial",
    ".download",
    ".crdownload",
    ".tmp",
    ".ytdl",
    ".aria2",
    ".f4v_frag",
)
_ARTIFACT_INFIXES = (
    ".part.",
    ".partial.",
    ".download.",
    ".crdownload.",
    ".tmp.",
    ".ytdl.",
    ".aria2.",
)


def _is_video_suffix(p: Path) -> bool:
    return p.suffix.lower() in _VIDEO_EXT


def _looks_like_artifact(path: Path) -> bool:
    """Return True if the path name suggests a partial/incomplete download."""
    name = path.name.lower()
    if any(name.endswith(suf) for suf in _ARTIFACT_SUFFIXES):
        return True
    if any(marker in name for marker in _ARTIFACT_INFIXES):
        return True
    return False


def _iter_files(root: Path, patterns: Optional[Sequence[str]], max_depth: Optional[int]) -> Iterator[Path]:
    """Yield files under root matching any of the provided glob patterns. Case-insensitive on Windows."""
    import logging
    logger = logging.getLogger(__name__)

    root = Path(root).resolve()
    logger.info(f"_iter_files: Starting enumeration of {root}")
    logger.info(f"_iter_files: patterns={patterns}, max_depth={max_depth}")

    patterns = list(patterns or [])
    if not patterns:
        logger.info("_iter_files: No patterns specified, yielding all files")
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

    logger.info(f"_iter_files: Normalized patterns: {norm}")

    # On Windows, match case-insensitively by lowering names
    ci = sys.platform.startswith("win")
    logger.info(f"_iter_files: Case-insensitive matching: {ci}")

    file_count = 0
    dir_count = 0

    logger.info(f"_iter_files: Starting os.walk() on {root}")
    try:
        for dp, dn, fn in os.walk(root):
            dir_count += 1
            if dir_count % 100 == 0:
                logger.info(f"_iter_files: Walked {dir_count} directories, yielded {file_count} files so far")

            if max_depth is not None:
                rel = Path(dp).resolve().relative_to(root)
                depth = 0 if str(rel) == "." else len(rel.parts)
                if depth > max_depth:
                    dn[:] = []
                    continue

            for name in fn:
                to_match = name.lower() if ci else name
                if any(Path(to_match).match(p.lower() if ci else p) for p in norm):
                    file_count += 1
                    if file_count <= 10:  # Log first 10 matches
                        logger.debug(f"_iter_files: Yielding file #{file_count}: {name}")
                    yield Path(dp) / name

        logger.info(f"_iter_files: Completed. Walked {dir_count} directories, yielded {file_count} total files")
    except Exception as e:
        logger.error(f"_iter_files: Error during enumeration: {e}", exc_info=True)
        raise


def _blake3_full_file(path: Path, block: int = 1 << 20) -> str:
    """
    Compute full-file hash using BLAKE3 (faster than SHA-256).
    Falls back to SHA-256 if BLAKE3 not available.
    """
    if _BLAKE3_AVAILABLE:
        h = blake3.blake3()
    else:
        h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_file(path: Path, block: int = 1 << 20) -> str:
    """Legacy SHA-256 hashing (kept for backward compatibility)."""
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
    Enhanced sliding alignment (subset) average Hamming distance with adaptive thresholds.
    Supports cross-resolution matching by normalizing threshold based on content complexity.
    """
    if not a_sig or not b_sig:
        return None

    # Ensure A is the shorter sequence
    A, B = (a_sig, b_sig) if len(a_sig) <= len(b_sig) else (b_sig, a_sig)

    if len(A) < 2:  # Need at least 2 frames for meaningful comparison
        return None

    best_distance = None
    best_offset = -1

    # Calculate content complexity for adaptive thresholding
    def _estimate_complexity(sig):
        if len(sig) < 2:
            return 1.0
        # Estimate complexity based on frame-to-frame variation
        variations = []
        for i in range(len(sig) - 1):
            x = int(sig[i]) ^ int(sig[i + 1])
            variations.append(x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1"))
        return max(1.0, sum(variations) / len(variations) / 16.0)  # Normalize to 0-4 range

    complexity_factor = min(2.0, _estimate_complexity(A))
    adaptive_threshold = per_frame_thresh * complexity_factor

    # Try different alignment strategies
    strategies = [
        (1, 0),      # Standard 1:1 alignment
        (2, 0),      # Skip every other frame in B (handles different frame rates)
        (1, 1),      # Skip first frame in B (handles intro/outro differences)
    ]

    for step, start_offset in strategies:
        max_positions = (len(B) - start_offset - 1) // step + 1
        if max_positions < len(A):
            continue

        for base_offset in range(0, max_positions - len(A) + 1):
            total_distance = 0
            valid_comparisons = 0

            for i in range(len(A)):
                b_idx = start_offset + base_offset + (i * step)
                if b_idx >= len(B):
                    break

                x = int(A[i]) ^ int(B[b_idx])
                frame_distance = x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
                total_distance += frame_distance
                valid_comparisons += 1

            if valid_comparisons >= min(3, len(A)):  # Need minimum valid comparisons
                avg_distance = total_distance / valid_comparisons
                if best_distance is None or avg_distance < best_distance:
                    best_distance = avg_distance
                    best_offset = base_offset

    return best_distance if (best_distance is not None and best_distance <= adaptive_threshold) else None


def _normalized_path(path: Path) -> Path:
    """Normalize paths for consistent set membership."""
    try:
        return path.expanduser().resolve()
    except Exception:
        return path


def _effective_length(meta: VideoMeta) -> float:
    """
    Approximate comparable length for duration-based heuristics.
    Falls back to file size (MiB) when duration is unavailable.
    """
    if meta.duration and meta.duration > 0:
        return float(meta.duration)
    return max(1.0, float(meta.size) / float(1024 * 1024))


def _avg_signature_distance(sig_a: Sequence[int], sig_b: Sequence[int]) -> float:
    """Return average bit distance between two equal-length signatures."""
    if not sig_a or not sig_b:
        return float("inf")
    count = min(len(sig_a), len(sig_b))
    if count == 0:
        return float("inf")
    total = 0
    for a, b in zip(sig_a[:count], sig_b[:count]):
        x = int(a) ^ int(b)
        total += x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
    return total / count


def _subset_master_loser(a: VideoMeta, b: VideoMeta) -> Tuple[VideoMeta, VideoMeta]:
    """
    Order a pair so that the preferred "master" (longer, higher quality) is first.
    This ensures downstream grouping consistently surfaces the highest-quality asset.
    """
    def _key(vm: VideoMeta) -> Tuple[float, int, int, int]:
        duration = vm.duration if vm.duration is not None else -1.0
        bitrate = vm.video_bitrate or 0
        return (duration, vm.resolution_area, bitrate, vm.size)

    return (a, b) if _key(a) >= _key(b) else (b, a)


# -------------------------------------------------------------------------------------------------
# Main pipeline
# -------------------------------------------------------------------------------------------------

Meta = Union[FileMeta, VideoMeta]
GroupMap = Dict[str, List[Meta]]


def run_pipeline(
    root: Optional[Path] = None,
    *,
    roots: Optional[Sequence[Path]] = None,
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
    reporter = reporter or ProgressReporter(enable_dash=False)

    import logging
    logger = logging.getLogger(__name__)

    logger.info("=== run_pipeline() ENTRY ===")
    logger.info(f"Received {len(roots) if roots else 0} roots, max_depth={max_depth}, stages={selected_stages}")

    scan_roots: List[Path] = []
    if root is not None:
        scan_roots.append(Path(root))
    if roots:
        scan_roots.extend(Path(r) for r in roots)
    if not scan_roots:
        raise ValueError("run_pipeline requires at least one root directory")
    scan_roots = [p.expanduser().resolve() for p in scan_roots]
    logger.info(f"Resolved scan_roots: {scan_roots}")

    skip_norm: Set[Path] = {p.expanduser().resolve() for p in skip_paths} if skip_paths else set()
    logger.info(f"Exclusions: {len(skip_norm)} paths")

    reporter.set_stage_plan(_build_stage_plan(selected_stages))

    logger.info("Calling reporter.set_status()...")
    try:
        reporter.set_status("Enumerating files")
        logger.info("set_status() completed successfully")
    except Exception as e:
        logger.error(f"set_status() failed: {e}")
        raise

    logger.info("Calling reporter.start_stage()...")
    try:
        reporter.start_stage("discovering files", total=0)
        logger.info("start_stage() completed successfully")
    except Exception as e:
        logger.error(f"start_stage() failed: {e}")
        raise

    logger.info("Calling reporter.update_root_progress()...")
    try:
        reporter.update_root_progress(current=None, completed=0, total=len(scan_roots))
        logger.info("update_root_progress() completed successfully")
    except Exception as e:
        logger.error(f"update_root_progress() failed: {e}")
        raise

    files: List[Path] = []
    skipped_during_enum = 0
    artifact_skipped = 0
    discovery_bytes = 0
    for index, scan_root in enumerate(scan_roots, start=1):
        logger.info("=== File enumeration starting for root %d/%d: %s (patterns: %s, max_depth: %s) ===",
                    index, len(scan_roots), scan_root, patterns, max_depth)

        try:
            reporter.update_root_progress(current=scan_root, completed=index - 1, total=len(scan_roots))
            reporter.set_status(f"Discovering files under {scan_root}")
            logger.info("Reporter status updated successfully")
        except Exception as e:
            logger.error(f"Reporter update failed: {e}")
            raise

        file_count_at_start = len(files)
        logger.info(f"Starting _iter_files() generator for: {scan_root}")

        try:
            for file_idx, path in enumerate(_iter_files(scan_root, patterns, max_depth)):
                resolved = path.expanduser().resolve()
                if skip_norm and resolved in skip_norm:
                    skipped_during_enum += 1
                    continue
                if not cfg.include_partials and _looks_like_artifact(path):
                    artifact_skipped += 1
                    continue
                files.append(path)
                try:
                    discovery_bytes += path.stat().st_size
                except Exception:
                    pass

                # Frequent UI updates for better responsiveness
                if len(files) % 50 == 0:
                    reporter.update_discovery(
                        len(files),
                        skipped=skipped_during_enum,
                        artifacts=artifact_skipped,
                        bytes_total=discovery_bytes,
                    )

                # Log progress every 500 files
                if len(files) % 500 == 0:
                    logger.info(f"Discovered {len(files):,} files (current root: {file_idx + 1:,} files)")

                # Detailed log every 100 files for first 1000, then every 1000
                elif len(files) < 1000 and len(files) % 100 == 0:
                    logger.debug(f"Discovery progress: {len(files)} files found")
        except Exception as e:
            logger.error(f"Error during file enumeration: {e}", exc_info=True)
            raise

        files_from_this_root = len(files) - file_count_at_start
        logger.info(f"Completed root {index}/{len(scan_roots)}: found {files_from_this_root:,} files")

        try:
            reporter.update_root_progress(current=scan_root, completed=index, total=len(scan_roots))
        except Exception as e:
            logger.error(f"Root progress update failed: {e}")
            raise

    reporter.update_discovery(
        len(files),
        skipped=skipped_during_enum,
        artifacts=artifact_skipped,
        bytes_total=discovery_bytes,
    )
    logger.info(
        "File enumeration completed across %d root(s). Found %d files (skipped %d excluded paths, %d artifacts).",
        len(scan_roots),
        len(files),
        skipped_during_enum,
        artifact_skipped,
    )

    reporter.set_total_files(len(files))
    reporter.update_root_progress(current=None, completed=len(scan_roots), total=len(scan_roots))
    reporter.finish_stage("discovering files")
    reporter.start_stage("scanning files", total=len(files))
    reporter.set_status("Scanning files for metadata")
    reporter.update_stage_metrics("scanning files", queued=f"{len(files):,}")
    logger.info(f"Starting scanning stage with {cfg.threads} threads")

    metas: List[FileMeta] = []
    by_size: Dict[int, List[FileMeta]] = defaultdict(list)

    def scan_one(p: Path) -> FileMeta:
        try:
            st = p.stat()
            return FileMeta(path=p, size=int(st.st_size), mtime=float(st.st_mtime))
        except Exception:
            return FileMeta(path=p, size=0, mtime=0.0)

    total_bytes = 0
    video_bytes = 0

    if files:
        logger.info(f"Starting metadata scan of {len(files):,} files across {cfg.threads} thread(s)")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
            for idx, meta in enumerate(ex.map(scan_one, files), start=1):
                metas.append(meta)
                by_size[meta.size].append(meta)
                is_video = _is_video_suffix(meta.path)
                reporter.inc_scanned(1, bytes_added=meta.size, is_video=is_video)

                total_bytes += meta.size
                if is_video:
                    video_bytes += meta.size

                if idx % 50 == 0 or idx == len(files):
                    reporter.update_progress_periodically(idx, len(files))

                if idx % 500 == 0:
                    pct = (idx / len(files)) * 100 if files else 0
                    logger.info(f"Scanning: {idx:,}/{len(files):,} files ({pct:.1f}%)")

                if idx < 500 and idx % 100 == 0:
                    logger.debug(f"Scanned {idx} files...")

        reporter.update_progress_periodically(len(files), len(files), force_update=True)
        logger.info(
            "Scanning complete: processed %d files (%.2f GiB)",
            len(metas),
            total_bytes / (1024**3) if total_bytes else 0.0,
        )

    reporter.set_total_bytes(total_bytes)
    reporter.mark_video_bytes_total(video_bytes)
    reporter.update_stage_metrics(
        "scanning files",
        scanned=f"{len(metas):,}",
        data=f"{total_bytes / (1024**3):.2f} GiB",
    )
    reporter.finish_stage("scanning files")

    if reporter.should_quit():
        reporter.flush()
        return {}

    # -------------------------------------------
    # Q1: size buckets (optimization hint, NOT elimination)
    # -------------------------------------------
    # CRITICAL: Q1 is an optimization for exact duplicates, NOT an elimination stage
    # Visual duplicates (different encodings/resolutions/clips) have DIFFERENT sizes
    # ALL files must continue to Q2/Q3/Q4 for visual similarity detection
    size_buckets_for_q2: Dict[int, List[FileMeta]] = {}  # Size-matched groups (optimization hint)

    if 1 in selected_stages:
        logger.info("Starting Q1: size bucket analysis (optimization, not elimination)")
        reporter.set_status("Q1 size bucketing")
        reporter.start_stage("Q1 size bucketing", total=len(by_size))

        # Identify size-matched groups for Q2 optimization
        size_matched_count = 0
        unique_size_count = 0

        for idx, (size, bucket) in enumerate(by_size.items(), start=1):
            if len(bucket) > 1:
                size_buckets_for_q2[size] = bucket
                size_matched_count += len(bucket)
            else:
                unique_size_count += 1

            if idx % 250 == 0:
                reporter.update_progress_periodically(idx, len(by_size) or 1)

        reporter.update_progress_periodically(len(by_size), len(by_size) or 1, force_update=True)
        reporter.update_stage_metrics(
            "Q1 size bucketing",
            buckets=len(by_size),
            size_matched=f"{size_matched_count:,}",
            unique_sizes=f"{unique_size_count:,}",
        )

        # Log findings
        logger.info(f"Q1 completed: {size_matched_count:,} files in {len(size_buckets_for_q2):,} size-matched groups")
        logger.info(f"Q1: {unique_size_count:,} files have unique sizes (still processed for visual similarity)")
        reporter.add_log(f"Q1: {size_matched_count:,} files in size-matched groups (exact duplicate candidates)")
        reporter.add_log(f"Q1: {unique_size_count:,} unique-sized files continue to visual stages")

        reporter.finish_stage("Q1 size bucketing")
    else:
        reporter.set_status("Skipping Q1 (size buckets disabled)")

    # ALL files continue to Q2 (nothing eliminated based on size alone!)
    all_candidates = metas

    groups: GroupMap = {}
    excluded_after_q2: Set[Path] = set()
    excluded_after_q3: Set[Path] = set()
    excluded_after_q4: Set[Path] = set()
    excluded_after_q5: Set[Path] = set()
    excluded_after_q6: Set[Path] = set()
    excluded_after_q7: Set[Path] = set()

    # -------------------------------------------------------
    # Q2: partial (blake3 slices) -> full sha256 on collisions
    # Smart ordering: prioritize size-matched groups for early exact-duplicate detection
    # -------------------------------------------------------
    if 2 in selected_stages and all_candidates:
        # Smart ordering: process size-matched files first for faster exact-duplicate detection
        priority_files = [f for bucket in size_buckets_for_q2.values() for f in bucket]
        remaining_files = [f for f in all_candidates if f not in priority_files]
        q2_candidates = priority_files + remaining_files

        logger.info(f"Starting Q2: partial hashing for {len(q2_candidates):,} files ({len(priority_files):,} priority, {len(remaining_files):,} remaining)")
        reporter.set_status("Q2 partial hashing")
        reporter.start_stage("Q2 partial", total=len(q2_candidates))
        reporter.set_hash_total(len(q2_candidates))

        partial_map: Dict[str, List[FileMeta]] = defaultdict(list)

        def _do_partial(m: FileMeta) -> Tuple[FileMeta, str]:
            # Avoid problematic blocking calls in thread workers
            # Skip: reporter.wait_if_paused() and reporter.should_quit() to prevent deadlocks
            sig = _blake3_partial_hex(m.path, head=1 << 20, tail=1 << 20, mid=0)
            # Safe call: simple counter increment (only catch threading-related exceptions)
            try:
                reporter.inc_hashed(1, cache_hit=False)
            except (RuntimeError, threading.ThreadError, AttributeError):
                pass  # Only catch specific UI threading issues
            return m, sig

        # Multi-threaded partial hashing with progress tracking
        logger.info(f"Starting partial hash computation for {len(q2_candidates):,} files using {cfg.threads} threads")

        # Thread-safe counter for progress
        completed = threading.Lock()
        completed_count = [0]

        def _do_partial_tracked(m: FileMeta) -> Tuple[FileMeta, str]:
            result = _do_partial(m)
            # Update counter atomically
            with completed:
                completed_count[0] += 1
                current = completed_count[0]

                # Log progress every 100 files
                if current % 100 == 0:
                    pct = (current / len(q2_candidates)) * 100
                    logger.info(f"Partial hashing: {current:,}/{len(q2_candidates):,} ({pct:.1f}%) - {cfg.threads} workers")

                # Update UI every 20 files
                if current % 20 == 0:
                    reporter.update_progress_periodically(current, len(q2_candidates))

            return result

        # Execute with thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.threads) as ex:
            for m_result, sig in ex.map(_do_partial_tracked, q2_candidates):
                partial_map[sig].append(m_result)

        # Final update
        reporter.update_progress_periodically(len(q2_candidates), len(q2_candidates), force_update=True)
        logger.info(f"Partial hashing complete: {len(partial_map):,} unique signatures using {cfg.threads} threads")
        reporter.update_stage_metrics(
            "Q2 partial",
            candidates=f"{len(q2_candidates):,}",
            unique=f"{len(partial_map):,}",
        )
        reporter.finish_stage("Q2 partial")

        if reporter.should_quit():
            reporter.flush();
            return groups

        # Escalate only partial buckets that still collide
        to_full: List[FileMeta] = [m for lst in partial_map.values() if len(lst) > 1 for m in lst]

        reporter.start_stage("Q2 full hash", total=len(to_full))
        reporter.set_status("Q2 full hash (BLAKE3/SHA-256)")
        reporter.set_hash_total(len(to_full))

        by_hash: Dict[str, List[FileMeta]] = defaultdict(list)

        def _do_full(m: FileMeta) -> Tuple[FileMeta, Optional[str], bool]:
            # Avoid problematic blocking calls in thread workers
            # Skip: reporter.wait_if_paused() and reporter.should_quit() to prevent deadlocks
            # Try cache first (check both blake3_full and legacy sha256)
            full_hash = None
            try:
                if cache:
                    # Try BLAKE3 cache first
                    full_hash = cache.get_field(m.path, m.size, m.mtime, "blake3_full")  # type: ignore[attr-defined]
                    if not full_hash:
                        # Fall back to SHA256 cache (backward compatibility)
                        full_hash = cache.get_field(m.path, m.size, m.mtime, "sha256")  # type: ignore[attr-defined]
            except Exception:
                full_hash = None
            if full_hash:
                # Safe call: simple counter increment
                try:
                    reporter.inc_hashed(1, cache_hit=True)
                except (RuntimeError, threading.ThreadError, AttributeError):
                    pass  # Only catch specific UI threading issues
                return m, full_hash, True
            try:
                # Use BLAKE3 for new hashes (faster)
                full_hash = _blake3_full_file(m.path)
                if full_hash and cache:
                    try:
                        # Store with blake3_full field (or sha256 if BLAKE3 unavailable)
                        field_name = "blake3_full" if _BLAKE3_AVAILABLE else "sha256"
                        cache.put_field(m.path, m.size, m.mtime, field_name, full_hash)
                    except Exception:
                        pass
                # Safe call: simple counter increment
                try:
                    reporter.inc_hashed(1, cache_hit=False)
                except (RuntimeError, threading.ThreadError, AttributeError):
                    pass  # Only catch specific UI threading issues
                return m, full_hash, False
            except Exception:
                # Safe call: simple counter increment for failed attempts
                try:
                    reporter.inc_hashed(1, cache_hit=False)
                except (RuntimeError, threading.ThreadError, AttributeError):
                    pass  # Only catch specific UI threading issues
                return m, None, False

        if to_full:
            # Multi-threaded full hash computation with progress tracking
            hash_algo = "BLAKE3" if _BLAKE3_AVAILABLE else "SHA-256"
            logger.info(f"Starting {hash_algo} full hash computation for {len(to_full):,} files using {cfg.threads} threads")

            # Thread-safe counter for progress
            completed = threading.Lock()
            completed_count = [0]  # Use list for mutability in closure

            def _do_full_tracked(m: FileMeta) -> Tuple[FileMeta, Optional[str], bool]:
                result = _do_full(m)
                # Update counter atomically
                with completed:
                    completed_count[0] += 1
                    current = completed_count[0]

                    # Log progress every 50 files
                    if current % 50 == 0:
                        pct = (current / len(to_full)) * 100
                        logger.info(f"{hash_algo} hashing: {current:,}/{len(to_full):,} ({pct:.1f}%) - {cfg.threads} workers")

                    # Update UI every 10 files
                    if current % 10 == 0:
                        reporter.update_progress_periodically(current, len(to_full))

                return result

            # Execute with thread pool
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.threads) as ex:
                for m_result, full_hash, _hit in ex.map(_do_full_tracked, to_full):
                    if full_hash:
                        by_hash[full_hash].append(m_result)

            # Final update
        reporter.update_progress_periodically(len(to_full), len(to_full), force_update=True)
        hash_algo = "BLAKE3" if _BLAKE3_AVAILABLE else "SHA-256"
        logger.info(f"{hash_algo} complete: {len(by_hash):,} unique full hashes using {cfg.threads} threads")

        # Form groups from exact hashes and mark **all members** excluded for later stages
        formed = 0
        duplicate_members = 0
        for h, lst in by_hash.items():
            if len(lst) > 1:
                groups[f"hash:{h}"] = lst
                for fm in lst:
                    excluded_after_q2.add(_normalized_path(fm.path))
                formed += 1
                duplicate_members += max(0, len(lst) - 1)
        if formed:
            reporter.inc_group("hash", formed)
        if duplicate_members:
            reporter.add_duplicate_files(duplicate_members)
        reporter.update_stage_metrics(
            "Q2 full hash",
            collisions=f"{len(to_full):,}",
            exact_groups=f"{formed:,}",
        )
        reporter.finish_stage("Q2 full hash")
        reporter.flush()
    elif 2 in selected_stages:
        reporter.set_status("Q2 skipped (no candidates)")
        reporter.mark_stage_skipped("Q2 partial")
        reporter.mark_stage_skipped("Q2 full hash")
    else:
        reporter.set_status("Skipping Q2 (stage disabled)")

    if reporter.should_quit():
        reporter.flush()
        return groups


    # ---------------------------------------------
    # Q3: ffprobe metadata (duration/format/codec...)
    # ---------------------------------------------
    if 3 in selected_stages:
        # Keep only videos not excluded by Q2
        vids_in: List[VideoMeta] = [
            VideoMeta(path=m.path, size=m.size, mtime=m.mtime)
            for m in metas
            if _is_video_suffix(m.path) and (_normalized_path(m.path) not in excluded_after_q2)
        ]

        if vids_in:
            reporter.set_status("Q3 metadata clustering")
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
            duplicate_members = 0
            gid = 0
            for comp in comps.values():
                if len(comp) > 1:
                    groups[f"meta:{gid}"] = comp
                    for vm in comp:
                        excluded_after_q3.add(_normalized_path(vm.path))
                    gid += 1
                    formed += 1
                    duplicate_members += len(comp) - 1
            if formed:
                reporter.inc_group("meta", formed)
            if duplicate_members:
                reporter.add_duplicate_files(duplicate_members)
            reporter.update_stage_metrics(
                "Q3 metadata",
                probed=f"{len(probed):,}",
                groups=f"{formed:,}",
                tolerance=f"{tol:.1f}s",
            )
            reporter.flush()

            video_for_q4 = probed
            reporter.finish_stage("Q3 metadata")
        else:
            reporter.set_status("Q3 skipped (no eligible videos)")
            video_for_q4 = []
            reporter.finish_stage("Q3 metadata", status="skipped")
    else:
        reporter.set_status("Skipping Q3 (stage disabled)")
        # Q3 not selected - allow Q4 on all videos not excluded by Q2
        video_for_q4 = [
            VideoMeta(path=m.path, size=m.size, mtime=m.mtime)
            for m in metas
            if _is_video_suffix(m.path) and (_normalized_path(m.path) not in excluded_after_q2)
        ]

    if reporter.should_quit():
        reporter.flush()
        return groups

    # ----------------------------------------------------------
    # Q4: pHash grouping & optional subset detection (expensive)
    # ----------------------------------------------------------
    if 4 in selected_stages and video_for_q4:
        # Exclude videos already grouped by Q3
        pending_for_q4 = [v for v in video_for_q4 if _normalized_path(v.path) not in excluded_after_q3]

        # Lazy import phash helpers here (avoid import-time errors in minimal env/tests)
        try:
            from vdedup.phash import compute_phash_signature, phash_distance  # type: ignore
        except Exception:
            compute_phash_signature = None  # type: ignore
            phash_distance = None  # type: ignore

        if compute_phash_signature and phash_distance and pending_for_q4:
            reporter.set_status("Q4 visual similarity analysis")
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
            duplicate_members = 0
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
                        for vm in grp:
                            excluded_after_q4.add(_normalized_path(vm.path))
                        gid += 1
                        formed_phash += 1
                        duplicate_members += len(grp) - 1
            if formed_phash:
                reporter.inc_group("phash", formed_phash)
            reporter.update_stage_metrics(
                "Q4 pHash",
                signatures=f"{len(phashed):,}",
                groups=f"{formed_phash:,}",
            )
            reporter.flush()

            # Enhanced subset detection with cross-resolution support
            formed_subset = 0  # Initialize before conditional block
            if cfg.subset_detect and phashed:
                gid = 0
                vids_sorted = sorted([v for v in phashed if v.duration], key=lambda v: v.duration or 0.0)

                # Group videos by resolution for more targeted comparisons
                by_resolution = {}
                for v in vids_sorted:
                    res_key = (v.width or 0, v.height or 0)
                    if res_key not in by_resolution:
                        by_resolution[res_key] = []
                    by_resolution[res_key].append(v)

                # Compare within and across resolution groups
                all_pairs = []
                for res1, vids1 in by_resolution.items():
                    for res2, vids2 in by_resolution.items():
                        # Allow cross-resolution comparison with adjusted ratio thresholds
                        res_factor = 1.0
                        if res1 != res2 and res1[0] > 0 and res2[0] > 0:
                            # Adjust threshold for different resolutions
                            area1, area2 = res1[0] * res1[1], res2[0] * res2[1]
                            res_factor = min(2.0, max(0.5, area2 / area1)) if area1 > 0 else 1.0

                        for v1 in vids1:
                            for v2 in vids2:
                                if v1.path == v2.path:
                                    continue
                                if v1.duration and v2.duration and v1.duration < v2.duration:
                                    all_pairs.append((v1, v2, res_factor))

                # Process all potential subset pairs
                subset_consumed: Set[Path] = set()
                for short, long, res_factor in all_pairs:
                    short_norm = _normalized_path(short.path)
                    if short_norm in subset_consumed:
                        continue

                    if not short.duration or not long.duration:
                        continue

                    ratio = short.duration / long.duration
                    adjusted_min_ratio = cfg.subset_min_ratio / res_factor

                    if ratio < adjusted_min_ratio or ratio > 0.95:  # Skip if too similar (likely same content)
                        continue

                    # Use enhanced alignable distance with resolution awareness
                    best = _alignable_distance(short.phash_signature, long.phash_signature, cfg.subset_frame_threshold)
                    if best is not None:
                        master, loser = _subset_master_loser(short, long)
                        groups[f"subset:{gid}"] = [master, loser]
                        subset_consumed.add(short_norm)
                        excluded_after_q4.add(_normalized_path(short.path))
                        gid += 1
                        formed_subset += 1
                        duplicate_members += 1

            if formed_subset:
                reporter.inc_group("subset", formed_subset)
                reporter.flush()
            if duplicate_members:
                reporter.add_duplicate_files(duplicate_members)
            reporter.update_stage_metrics(
                "Q4 pHash",
                subset_matches=f"{formed_subset:,}",
            )
            reporter.finish_stage("Q4 pHash")
        else:
            reporter.set_status("Q4 skipped (no analyzable videos)")
            reporter.mark_stage_skipped("Q4 pHash")
    elif 4 in selected_stages:
        reporter.set_status("Q4 skipped (stage disabled by upstream filters)")
        reporter.mark_stage_skipped("Q4 pHash")

    # ----------------------------------------------------------
    # Q5: Scene-aware fingerprinting (advanced visual matching)
    # ----------------------------------------------------------
    if 5 in selected_stages and video_for_q4:
        pending_for_q5 = [
            v
            for v in video_for_q4
            if _normalized_path(v.path) not in excluded_after_q3
            and _normalized_path(v.path) not in excluded_after_q4
        ]

        try:
            from vdedup.phash import compute_scene_fingerprint  # type: ignore
        except Exception:
            compute_scene_fingerprint = None  # type: ignore

        if compute_scene_fingerprint and pending_for_q5:
            reporter.set_status("Q5 scene fingerprinting")
            reporter.start_stage("Q5 scene", total=len(pending_for_q5))
            reporter.set_hash_total(len(pending_for_q5))

            scene_fps: Dict[Path, Tuple[VideoMeta, Tuple[int, ...]]] = {}

            def _do_scene(vm: VideoMeta) -> Tuple[VideoMeta, Optional[Tuple[int, ...]]]:
                reporter.wait_if_paused()
                if reporter.should_quit():
                    return vm, None
                sig = compute_scene_fingerprint(vm.path, max_scenes=max(12, cfg.phash_frames * 2), gpu=cfg.gpu)
                reporter.inc_hashed(1, cache_hit=False)
                return vm, sig

            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for vm, sig in ex.map(_do_scene, pending_for_q5):
                    if sig:
                        scene_fps[_normalized_path(vm.path)] = (vm, sig)

            reporter.update_stage_metrics("Q5 scene", descriptors=f"{len(scene_fps):,}")

            entries = list(scene_fps.values())
            pairs_evaluated = 0
            formed_scene = 0
            duplicate_members = 0
            subset_pairs = 0
            gid = 0
            consumed: Set[Path] = set()
            subset_consumed: Set[Path] = set()
            per_scene_thresh = max(8, int(cfg.subset_frame_threshold * 1.2))

            for i in range(len(entries)):
                vm_a, sig_a = entries[i]
                path_a = _normalized_path(vm_a.path)
                if path_a in consumed or not sig_a:
                    continue
                for j in range(i + 1, len(entries)):
                    vm_b, sig_b = entries[j]
                    path_b = _normalized_path(vm_b.path)
                    if path_b in consumed or not sig_b:
                        continue
                    if abs(len(sig_a) - len(sig_b)) > 6:
                        continue

                    pairs_evaluated += 1
                    len_a = _effective_length(vm_a)
                    len_b = _effective_length(vm_b)
                    diff = abs(len_a - len_b)
                    max_len = max(len_a, len_b)

                    if diff <= max(5.0, 0.05 * max_len):
                        avg_dist = _avg_signature_distance(sig_a, sig_b)
                        if avg_dist <= per_scene_thresh:
                            groups[f"scene:{gid}"] = [vm_a, vm_b]
                            consumed.update({path_a, path_b})
                            excluded_after_q5.update({path_a, path_b})
                            formed_scene += 1
                            duplicate_members += 1
                            gid += 1
                            break
                    else:
                        ratio = min(len_a, len_b) / max_len if max_len else 0.0
                        if ratio < max(cfg.subset_min_ratio, 0.2):
                            continue
                        short_vm = vm_a if len_a <= len_b else vm_b
                        long_vm = vm_b if short_vm is vm_a else vm_a
                        short_norm = _normalized_path(short_vm.path)
                        if short_norm in subset_consumed:
                            continue
                        short_sig = sig_a if short_vm is vm_a else sig_b
                        long_sig = sig_b if short_vm is vm_a else sig_a
                        best = _alignable_distance(short_sig, long_sig, per_scene_thresh)
                        if best is not None:
                            master, loser = _subset_master_loser(short_vm, long_vm)
                            groups[f"scene-sub:{gid}"] = [master, loser]
                            consumed.add(short_norm)
                            subset_consumed.add(short_norm)
                            excluded_after_q5.add(short_norm)
                            formed_scene += 1
                            subset_pairs += 1
                            duplicate_members += 1
                            gid += 1
                            continue

            if formed_scene:
                reporter.inc_group("scene", formed_scene)
            if subset_pairs:
                reporter.inc_group("subset", subset_pairs)
            if duplicate_members:
                reporter.add_duplicate_files(duplicate_members)
            reporter.update_stage_metrics(
                "Q5 scene",
                comparisons=f"{pairs_evaluated:,}",
                groups=f"{formed_scene:,}",
                subset_pairs=f"{subset_pairs:,}",
            )
            reporter.finish_stage("Q5 scene")
        else:
            reporter.set_status("Q5 skipped (no analyzable videos)")
            reporter.mark_stage_skipped("Q5 scene")
    elif 5 in selected_stages:
        reporter.set_status("Q5 skipped (stage disabled or no videos)")
        reporter.mark_stage_skipped("Q5 scene")

    if reporter.should_quit():
        reporter.flush()
        return groups

    # ----------------------------------------------------------
    # Q6: Audio fingerprinting and analysis (experimental)
    # ----------------------------------------------------------
    if 6 in selected_stages and video_for_q4:
        pending_for_q6 = [
            v
            for v in video_for_q4
            if _normalized_path(v.path) not in excluded_after_q3
            and _normalized_path(v.path) not in excluded_after_q4
            and _normalized_path(v.path) not in excluded_after_q5
        ]

        try:
            from vdedup.audio import compute_audio_fingerprint  # type: ignore
        except Exception:
            compute_audio_fingerprint = None  # type: ignore

        if compute_audio_fingerprint and pending_for_q6:
            reporter.set_status("Q6 audio fingerprinting")
            reporter.start_stage("Q6 audio", total=len(pending_for_q6))
            reporter.set_hash_total(len(pending_for_q6))

            audio_fps: Dict[Path, Tuple[VideoMeta, Tuple[int, ...]]] = {}

            def _do_audio(vm: VideoMeta) -> Tuple[VideoMeta, Optional[Tuple[int, ...]]]:
                reporter.wait_if_paused()
                if reporter.should_quit():
                    return vm, None
                sig = compute_audio_fingerprint(vm.path)
                reporter.inc_hashed(1, cache_hit=False)
                return vm, sig

            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for vm, sig in ex.map(_do_audio, pending_for_q6):
                    if sig:
                        audio_fps[_normalized_path(vm.path)] = (vm, sig)

            reporter.update_stage_metrics("Q6 audio", descriptors=f"{len(audio_fps):,}")

            entries = list(audio_fps.values())
            formed_audio = 0
            audio_subset_pairs = 0
            duplicate_members = 0
            comparisons = 0
            processed_audio: Set[Path] = set()
            subset_audio_consumed: Set[Path] = set()
            audio_dup_thresh = 12
            audio_subset_thresh = max(14, int(cfg.subset_frame_threshold * 1.5))
            gid = 0

            for i in range(len(entries)):
                vm_a, sig_a = entries[i]
                path_a = _normalized_path(vm_a.path)
                if path_a in processed_audio or not sig_a:
                    continue
                for j in range(i + 1, len(entries)):
                    vm_b, sig_b = entries[j]
                    path_b = _normalized_path(vm_b.path)
                    if path_b in processed_audio or not sig_b:
                        continue
                    if abs(len(sig_a) - len(sig_b)) > 10:
                        continue
                    comparisons += 1
                    len_a = _effective_length(vm_a)
                    len_b = _effective_length(vm_b)
                    diff = abs(len_a - len_b)
                    max_len = max(len_a, len_b)

                    if diff <= max(6.0, 0.08 * max_len):
                        avg_dist = _avg_signature_distance(sig_a, sig_b)
                        if avg_dist <= audio_dup_thresh:
                            groups[f"audio:{gid}"] = [vm_a, vm_b]
                            processed_audio.update({path_a, path_b})
                            excluded_after_q6.update({path_a, path_b})
                            formed_audio += 1
                            duplicate_members += 1
                            gid += 1
                            break
                    else:
                        ratio = min(len_a, len_b) / max_len if max_len else 0.0
                        if ratio < max(cfg.subset_min_ratio, 0.25):
                            continue
                        short_vm = vm_a if len_a <= len_b else vm_b
                        long_vm = vm_b if short_vm is vm_a else vm_a
                        short_norm = _normalized_path(short_vm.path)
                        if short_norm in subset_audio_consumed:
                            continue
                        short_sig = sig_a if short_vm is vm_a else sig_b
                        long_sig = sig_b if short_vm is vm_a else sig_a
                        best = _alignable_distance(short_sig, long_sig, audio_subset_thresh)
                        if best is not None:
                            master, loser = _subset_master_loser(short_vm, long_vm)
                            groups[f"audio-sub:{gid}"] = [master, loser]
                            processed_audio.add(short_norm)
                            subset_audio_consumed.add(short_norm)
                            excluded_after_q6.add(short_norm)
                            formed_audio += 1
                            duplicate_members += 1
                            audio_subset_pairs += 1
                            gid += 1
                            continue

            if formed_audio:
                reporter.inc_group("audio", formed_audio)
            if audio_subset_pairs:
                reporter.inc_group("subset", audio_subset_pairs)
            if duplicate_members:
                reporter.add_duplicate_files(duplicate_members)
            reporter.update_stage_metrics(
                "Q6 audio",
                comparisons=f"{comparisons:,}",
                groups=f"{formed_audio:,}",
                subset_pairs=f"{audio_subset_pairs:,}",
            )
            reporter.finish_stage("Q6 audio")
        else:
            reporter.set_status("Q6 skipped (no analyzable audio)")
            reporter.mark_stage_skipped("Q6 audio")
    elif 6 in selected_stages:
        reporter.set_status("Q6 skipped (stage disabled or no videos)")
        reporter.mark_stage_skipped("Q6 audio")

    if reporter.should_quit():
        reporter.flush()
        return groups

    # ----------------------------------------------------------
    # Q7: Advanced content analysis (experimental)
    # ----------------------------------------------------------
    if 7 in selected_stages and video_for_q4:
        pending_for_q7 = [
            v
            for v in video_for_q4
            if _normalized_path(v.path) not in excluded_after_q3
            and _normalized_path(v.path) not in excluded_after_q4
            and _normalized_path(v.path) not in excluded_after_q5
            and _normalized_path(v.path) not in excluded_after_q6
        ]

        try:
            from vdedup.phash import compute_timeline_signature  # type: ignore
        except Exception:
            compute_timeline_signature = None  # type: ignore

        if compute_timeline_signature and pending_for_q7:
            reporter.set_status("Q7 timeline analysis")
            reporter.start_stage("Q7 timeline", total=len(pending_for_q7))
            reporter.set_hash_total(len(pending_for_q7))

            timeline_fps: Dict[Path, Tuple[VideoMeta, Tuple[int, ...]]] = {}

            def _do_timeline(vm: VideoMeta) -> Tuple[VideoMeta, Optional[Tuple[int, ...]]]:
                reporter.wait_if_paused()
                if reporter.should_quit():
                    return vm, None
                sig = compute_timeline_signature(vm.path, fps=2.0, max_frames=120, gpu=cfg.gpu)
                reporter.inc_hashed(1, cache_hit=False)
                return vm, sig

            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(cfg.threads))) as ex:
                for vm, sig in ex.map(_do_timeline, pending_for_q7):
                    if sig:
                        timeline_fps[_normalized_path(vm.path)] = (vm, sig)

            reporter.update_stage_metrics("Q7 timeline", descriptors=f"{len(timeline_fps):,}")

            entries = list(timeline_fps.values())
            formed_timeline = 0
            timeline_subset_pairs = 0
            duplicate_members = 0
            comparisons = 0
            processed_timeline: Set[Path] = set()
            timeline_subset_consumed: Set[Path] = set()
            gid = 0
            timeline_dup_thresh = max(10, int(cfg.phash_threshold))
            timeline_subset_thresh = max(12, int(cfg.subset_frame_threshold * 1.1))

            for i in range(len(entries)):
                vm_a, sig_a = entries[i]
                path_a = _normalized_path(vm_a.path)
                if path_a in processed_timeline or not sig_a:
                    continue
                for j in range(i + 1, len(entries)):
                    vm_b, sig_b = entries[j]
                    path_b = _normalized_path(vm_b.path)
                    if path_b in processed_timeline or not sig_b:
                        continue
                    comparisons += 1
                    len_a = _effective_length(vm_a)
                    len_b = _effective_length(vm_b)
                    diff = abs(len_a - len_b)
                    max_len = max(len_a, len_b)

                    if diff <= max(8.0, 0.04 * max_len):
                        avg_dist = _avg_signature_distance(sig_a, sig_b)
                        if avg_dist <= timeline_dup_thresh:
                            groups[f"timeline:{gid}"] = [vm_a, vm_b]
                            processed_timeline.update({path_a, path_b})
                            excluded_after_q7.update({path_a, path_b})
                            formed_timeline += 1
                            duplicate_members += 1
                            gid += 1
                            break
                    else:
                        ratio = min(len_a, len_b) / max_len if max_len else 0.0
                        if ratio < max(cfg.subset_min_ratio, 0.3):
                            continue
                        short_vm = vm_a if len_a <= len_b else vm_b
                        long_vm = vm_b if short_vm is vm_a else vm_a
                        short_norm = _normalized_path(short_vm.path)
                        if short_norm in timeline_subset_consumed:
                            continue
                        short_sig = sig_a if short_vm is vm_a else sig_b
                        long_sig = sig_b if short_vm is vm_a else sig_a
                        best = _alignable_distance(short_sig, long_sig, timeline_subset_thresh)
                        if best is not None:
                            master, loser = _subset_master_loser(short_vm, long_vm)
                            groups[f"timeline-sub:{gid}"] = [master, loser]
                            processed_timeline.add(short_norm)
                            timeline_subset_consumed.add(short_norm)
                            excluded_after_q7.add(short_norm)
                            formed_timeline += 1
                            timeline_subset_pairs += 1
                            duplicate_members += 1
                            gid += 1
                            continue

            if formed_timeline:
                reporter.inc_group("timeline", formed_timeline)
            if timeline_subset_pairs:
                reporter.inc_group("subset", timeline_subset_pairs)
            if duplicate_members:
                reporter.add_duplicate_files(duplicate_members)
            reporter.update_stage_metrics(
                "Q7 timeline",
                comparisons=f"{comparisons:,}",
                groups=f"{formed_timeline:,}",
                subset_pairs=f"{timeline_subset_pairs:,}",
            )
            reporter.finish_stage("Q7 timeline")
        else:
            reporter.set_status("Q7 skipped (no analyzable timelines)")
            reporter.mark_stage_skipped("Q7 timeline")
    elif 7 in selected_stages:
        reporter.set_status("Q7 skipped (stage disabled or no videos)")
        reporter.mark_stage_skipped("Q7 timeline")

    # Final flush of results (CLI will compute losers/bytes after keep-policy)
    reporter.set_status("Pipeline stages complete")
    reporter.set_results(dup_groups=len(groups), losers_count=0, bytes_total=0)
    reporter.flush()
    return groups
