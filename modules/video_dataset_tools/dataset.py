#!/usr/bin/env python3
"""
Video dataset toolkit: download master videos, generate rich overlapping variants,
and emit a reproducible truth manifest. Designed for vdedup and similar pipelines.

Highlights
- Seeded randomness so the same seed reproduces the exact set of variants
- Auto-generate mapping/id files from a URL list with master-video-N naming
- Extensive CLI help with short/long flags for every argument
- Controls for variant count, overlap probability, layout (per-master vs flat)
- Truth manifest (truth.json) that maps each key to original and all variants
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .transformations import (
    change_audio_bitrate,
    change_video_bitrate,
    remove_audio,
    scale_video,
    trim_video,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrimSpec:
    """Represents a clip to extract from a video."""

    name: str
    start: float
    duration: float


@dataclass(frozen=True)
class VariantSpec:
    """Represents a variant transformation."""

    name: str
    kind: str
    params: Dict[str, object]


@dataclass(frozen=True)
class RandomPlan:
    """Controls randomized overlapping variant creation."""

    seed: Optional[int]
    min_variants: int
    max_variants: int
    overlap_prob: float


class ProgressTracker:
    """Thread-safe counters for live UI and logging."""

    def __init__(self, total_keys: int = 0, board: object | None = None, workers: int = 1) -> None:
        self.total_keys = total_keys
        self.started = 0
        self.downloaded = 0
        self.det_variants = 0
        self.rand_variants = 0
        self.errors = 0
        self._lock = Lock()
        self._start_ts = time.time()
        self.board = board
        self.workers = max(1, workers)
        self.worker_state: Dict[int, Tuple[str, str]] = {i: ("idle", "-") for i in range(1, self.workers + 1)}
        if self.board:
            self._init_board()

    def _init_board(self) -> None:
        Stat = _lazy_stat_import()

        self.board.add_row(
            "progress",
            Stat("keys", f"0/{self.total_keys}", format_string="{}", no_expand=True, display_width=14),
            Stat("downloaded", 0, prefix="dl=", format_string="{}", no_expand=True, display_width=8),
            Stat("variants", (0, 0), prefix="var=", format_string="{}+{}", no_expand=True, display_width=10),
            Stat("errors", 0, prefix="err=", format_string="{}", color=self._warn_color, no_expand=True, display_width=6),
            Stat("rate", 0.0, prefix="rate=", format_string="{:.2f}/s", no_expand=True, display_width=12),
            Stat("elapsed", 0.0, prefix="t=", format_string="{:.1f}s", no_expand=True, display_width=10),
        )

        for wid in range(1, self.workers + 1):
            self.board.add_row(
                f"worker-{wid:02d}",
                Stat("id", f"W{wid:02d}", no_expand=True, display_width=5, color="1;36"),
                Stat("key", "-", prefix="key=", format_string="{}", no_expand=True, display_width=22),
                Stat("stage", "idle", prefix="stage=", format_string="{}", no_expand=True, display_width=14),
            )

    @staticmethod
    def _warn_color(value: object) -> str:
        try:
            return "1;31" if int(value) > 0 else ""
        except Exception:
            return ""

    def set_total(self, total_keys: int) -> None:
        with self._lock:
            self.total_keys = total_keys
        self._refresh()

    def on_start(self, _key: str) -> None:
        with self._lock:
            self.started += 1
        self._refresh()

    def on_download(self) -> None:
        with self._lock:
            self.downloaded += 1
        self._refresh()

    def on_variants(self, det_count: int, rand_count: int) -> None:
        with self._lock:
            self.det_variants += det_count
            self.rand_variants += rand_count
        self._refresh()

    def on_error(self) -> None:
        with self._lock:
            self.errors += 1
        self._refresh()

    def set_worker_stage(self, worker_id: int, key: str, stage: str) -> None:
        with self._lock:
            self.worker_state[worker_id] = (stage, key)
        self._refresh_worker(worker_id)

    def _refresh(self) -> None:
        if not self.board:
            return
        elapsed = max(0.001, time.time() - self._start_ts)
        rate = (self.det_variants + self.rand_variants) / elapsed
        self.board.update("progress", "keys", f"{self.started}/{self.total_keys or '?'}")
        self.board.update("progress", "downloaded", self.downloaded)
        self.board.update("progress", "variants", (self.det_variants, self.rand_variants))
        self.board.update("progress", "errors", self.errors)
        self.board.update("progress", "rate", rate)
        self.board.update("progress", "elapsed", elapsed)

    def _refresh_worker(self, worker_id: int) -> None:
        if not self.board:
            return
        stage, key = self.worker_state.get(worker_id, ("idle", "-"))
        line = f"worker-{worker_id:02d}"
        self.board.update(line, "key", key)
        self.board.update(line, "stage", stage)


def _lazy_stat_import():
    try:
        from termdash.components import Stat
        return Stat
    except Exception:
        pass
    # fallback to repo-local path
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.append(str(root))
    from modules.termdash.components import Stat
    return Stat


def _lazy_simpleboard_import():
    try:
        from termdash.simpleboard import SimpleBoard
        return SimpleBoard
    except Exception:
        pass
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.append(str(root))
    from modules.termdash.simpleboard import SimpleBoard
    return SimpleBoard


@contextmanager
def _board_runner(board: object):
    try:
        board.start()
        yield board
    finally:
        try:
            board.stop()
        except Exception:
            pass


def _maybe_start_ui(total_keys: int, workers: int) -> tuple[ProgressTracker | None, object]:
    try:
        SimpleBoard = _lazy_simpleboard_import()
    except Exception as exc:  # pragma: no cover - optional dep
        logger.warning("UI disabled; termdash unavailable (%s)", exc)
        return None, nullcontext()

    extra_rows = max(6, workers + 2)
    board = SimpleBoard(title="Video Dataset Generator", refresh_rate=0.2, reserve_extra_rows=extra_rows)
    tracker = ProgressTracker(total_keys, board=board, workers=workers)
    return tracker, _board_runner(board)


def ensure_yt_dlp() -> None:
    """Raise RuntimeError if yt-dlp is missing from PATH."""

    if not shutil.which("yt-dlp") and not shutil.which("yt_dlp"):
        raise RuntimeError(
            "yt-dlp not found in PATH. Install yt-dlp via pip, pipx, or your package manager."
        )


def ensure_ffmpeg() -> None:
    """Raise RuntimeError if ffmpeg is missing from PATH."""

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found in PATH. Install ffmpeg via your OS package manager or a static build."
        )


def load_keys(mapping_file: Path) -> List[str]:
    """Load opaque keys (one per line) from a text file, ignoring blanks."""

    with mapping_file.open("r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def load_id_map(id_map_file: Path) -> Dict[str, str]:
    """Load JSON mapping of key -> YouTube ID/URL, coercing both to strings."""

    with id_map_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {str(key): str(value) for key, value in data.items()}


def parse_urls_file(urls_file: Path) -> List[str]:
    """Read YouTube URLs (one per line), ignoring blanks and comments."""

    lines = urls_file.read_text(encoding="utf-8").splitlines()
    urls: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        urls.append(stripped)
    return urls


def _normalize_source(source: str) -> str:
    """Return a full URL for yt-dlp (accepts bare IDs or URLs)."""

    if source.startswith("http://") or source.startswith("https://"):
        return source
    return f"https://www.youtube.com/watch?v={source}"


def discover_random_urls(
    count: int,
    *,
    seed: Optional[int] = None,
    per_query: int = 12,
) -> List[str]:
    """Use yt-dlp search to discover random YouTube URLs deterministically.

    This issues lightweight search queries (no downloads) and collects unique video ids.
    """

    if count < 1:
        return []

    ensure_yt_dlp()

    query_pool = [
        "music",
        "news",
        "science",
        "documentary",
        "tutorial",
        "travel",
        "nature",
        "history",
        "technology",
        "gaming",
        "film",
        "sports",
        "interview",
        "conference",
        "review",
        "education",
        "art",
        "live",
        "comedy",
    ]

    rng = random.Random(seed)
    urls: List[str] = []
    seen: Set[str] = set()
    max_attempts = max(count * 3, 20)

    def _fetch_for_query(query: str) -> List[str]:
        cmd = [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "--skip-download",
            "--flat-playlist",
            "--dump-json",
            f"ytsearch{per_query}:{query}",
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise RuntimeError(
                f"yt-dlp search failed for query '{query}': {result.stderr.decode(errors='replace')}"
            )
        found: List[str] = []
        for line in result.stdout.decode(errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                vid = data.get("id")
                if vid:
                    found.append(_normalize_source(str(vid)))
            except Exception:
                continue
        return found

    attempts = 0
    while len(urls) < count and attempts < max_attempts:
        attempts += 1
        query = rng.choice(query_pool)
        for url in _fetch_for_query(query):
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= count:
                    break

    if len(urls) < count:
        raise RuntimeError(f"Only discovered {len(urls)} URLs (wanted {count}); try adjusting per-query or connectivity")
    return urls[:count]


def download_video(youtube_source: str, dest_dir: Path, key: str) -> Path:
    """
    Download a YouTube video with yt-dlp into dest_dir as `<key>.<ext>`.
    Existing non-empty files are reused. Returns the downloaded path.
    """

    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = [p for p in dest_dir.glob(f"{key}.*") if p.stat().st_size > 0]
    if existing:
        logger.info("Reusing existing download for %s: %s", key, existing[0])
        return existing[0]

    output_template = str(dest_dir / f"{key}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--merge-output-format",
        "mp4",
        "--format",
        "bestvideo+bestaudio/best",
        "-o",
        output_template,
        _normalize_source(youtube_source),
    ]
    logger.info("Downloading video for key %s", key)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"yt-dlp failed for {youtube_source} (key {key}): {stderr}")

    downloaded = list(dest_dir.glob(f"{key}.*"))
    if not downloaded:
        raise RuntimeError(f"yt-dlp did not produce an output file for key {key}")
    return downloaded[0]


def _trim_specs(extra: Sequence[TrimSpec]) -> List[TrimSpec]:
    """Return default trim specs plus any user-provided extras."""

    defaults = [
        TrimSpec("clip15", 0.0, 15.0),
        TrimSpec("clip10min", 0.0, 600.0),
        TrimSpec("clip36_45", 36.0, 9.0),
        TrimSpec("clip1023_7834", 1023.0, 7834.0 - 1023.0),
    ]
    return defaults + list(extra)


def _scale_specs() -> List[VariantSpec]:
    return [
        VariantSpec("360p", "scale", {"width": None, "height": 360}),
        VariantSpec("240p", "scale", {"width": None, "height": 240}),
    ]


def _audio_specs() -> List[VariantSpec]:
    return [
        VariantSpec("64k", "audio_bitrate", {"bitrate": "64k"}),
        VariantSpec("32k", "audio_bitrate", {"bitrate": "32k"}),
        VariantSpec("noaudio", "remove_audio", {}),
    ]


def _video_specs() -> List[VariantSpec]:
    return [
        VariantSpec("1M", "video_bitrate", {"bitrate": "1M", "crf": None}),
        VariantSpec("crf30", "video_bitrate", {"bitrate": None, "crf": 30}),
        VariantSpec("renamed", "copy", {}),
    ]


def create_variants(
    key: str,
    src_path: Path,
    dest_dir: Path,
    *,
    extra_trims: Sequence[TrimSpec] | None = None,
    ffmpeg_mode: str = "cpu",
    ffmpeg_threads: Optional[int] = None,
    flat_variants: bool = False,
) -> List[Path]:
    """
    Create deterministic baseline variants for `src_path`.
    If flat_variants is True, all variants are placed directly under dest_dir.
    """

    variant_dir = dest_dir if flat_variants else dest_dir / key
    variant_dir.mkdir(parents=True, exist_ok=True)
    produced: List[Path] = []

    # Trims
    for spec in _trim_specs(extra_trims or []):
        if spec.duration <= 0:
            continue
        out_file = variant_dir / f"{key}_{spec.name}.mp4"
        if out_file.exists():
            produced.append(out_file)
            continue
        try:
            trim_video(
                src_path,
                out_file,
                start=spec.start,
                duration=spec.duration,
                mode=ffmpeg_mode,
                threads=ffmpeg_threads,
            )
            produced.append(out_file)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to create %s: %s", out_file, exc)

    # Scaling
    for spec in _scale_specs():
        out_file = variant_dir / f"{key}_{spec.name}.mp4"
        if out_file.exists():
            produced.append(out_file)
            continue
        try:
            scale_video(
                src_path,
                out_file,
                width=spec.params.get("width"),
                height=spec.params.get("height"),
                keep_aspect=True,
                mode=ffmpeg_mode,
                threads=ffmpeg_threads,
            )
            produced.append(out_file)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to create %s: %s", out_file, exc)

    # Audio tweaks
    for spec in _audio_specs():
        suffix = spec.name
        out_file = variant_dir / f"{key}_{suffix}.mp4"
        if out_file.exists():
            produced.append(out_file)
            continue
        try:
            if spec.kind == "audio_bitrate":
                change_audio_bitrate(src_path, out_file, bitrate=str(spec.params["bitrate"]))
            elif spec.kind == "remove_audio":
                remove_audio(src_path, out_file)
            produced.append(out_file)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to create %s: %s", out_file, exc)

    # Video bitrate / CRF / rename
    for spec in _video_specs():
        suffix = spec.name
        if spec.kind == "copy":
            out_file = variant_dir / f"{key}_renamed.mp4"
        else:
            out_file = variant_dir / f"{key}_{suffix}.mp4"

        if out_file.exists():
            produced.append(out_file)
            continue

        try:
            if spec.kind == "video_bitrate":
                change_video_bitrate(
                    src_path,
                    out_file,
                    bitrate=spec.params.get("bitrate"),
                    crf=spec.params.get("crf"),
                    mode=ffmpeg_mode,
                    threads=ffmpeg_threads,
                )
            elif spec.kind == "copy":
                shutil.copy2(src_path, out_file)
            produced.append(out_file)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to create %s: %s", out_file, exc)

    return produced


def _run_combo_ffmpeg(args: list[str]) -> None:
    logger.debug("Running ffmpeg: %s", " ".join(args))
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg command failed (code {result.returncode}): {' '.join(args)}\n"
            f"stderr: {result.stderr.decode(errors='replace')}"
        )


def _render_combo_variant(
    src_path: Path,
    dest_path: Path,
    *,
    trim: Optional[TrimSpec],
    scale: Optional[VariantSpec],
    audio: Optional[VariantSpec],
    video: Optional[VariantSpec],
    mode: str,
    threads: Optional[int],
) -> None:
    """Apply multiple manipulations in one ffmpeg call to ensure overlap."""

    args: list[str] = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if mode == "cuda":
        args += ["-hwaccel", "cuda"]
    if trim:
        args += ["-ss", str(max(0.0, trim.start))]
    args += ["-i", str(src_path)]
    if trim and trim.duration > 0:
        args += ["-t", str(trim.duration)]

    filters: List[str] = []
    if scale:
        w = scale.params.get("width", -1)
        h = scale.params.get("height", -1)
        filters.append(f"scale={w}:{h}")
    if filters:
        args += ["-vf", ",".join(filters)]

    if video:
        encoder = "h264_nvenc" if mode == "cuda" else "libx264"
        args += ["-c:v", encoder]
        if video.params.get("bitrate"):
            args += ["-b:v", str(video.params.get("bitrate"))]
        if video.params.get("crf") is not None:
            args += ["-crf", str(video.params.get("crf"))]
        args += ["-preset", "medium"]
    else:
        args += ["-c:v", "copy"]

    if audio:
        if audio.kind == "remove_audio":
            args += ["-an"]
        elif audio.kind == "audio_bitrate":
            args += ["-c:a", "aac", "-b:a", str(audio.params.get("bitrate", "64k"))]
    else:
        args += ["-c:a", "copy"]

    if threads is not None:
        args += ["-threads", str(threads)]

    args.append(str(dest_path))
    _run_combo_ffmpeg(args)
    logger.info("Created combo variant: %s", dest_path)


def _plan_random_variants(key: str, plan: RandomPlan) -> List[Dict[str, Optional[VariantSpec]]]:
    """Build a deterministic list of randomized variant recipes for a key."""

    base_seed = plan.seed if plan.seed is not None else random.randint(0, 2**32 - 1)
    rng = random.Random()
    # Derive per-key offset using a string seed to satisfy Random.seed types
    rng.seed(f"{base_seed}:{key}")
    count = rng.randint(plan.min_variants, plan.max_variants)
    recipes: List[Dict[str, Optional[VariantSpec]]] = []

    for _ in range(count):
        # Choose building blocks
        trim_choice = None
        if rng.random() < 0.9:
            start = rng.uniform(0, 180)
            duration = rng.uniform(8, 120)
            trim_choice = TrimSpec(f"rand_trim_{int(start)}_{int(duration)}", start, duration)

        scale_choice = None
        if rng.random() < 0.8:
            scale_choice = rng.choice(_scale_specs())

        audio_choice = None
        audio_pick = rng.random()
        if audio_pick < 0.4:
            audio_choice = VariantSpec("noaudio", "remove_audio", {})
        elif audio_pick < 0.75:
            audio_choice = VariantSpec("64k", "audio_bitrate", {"bitrate": "64k"})

        video_choice = None
        if rng.random() < 0.85:
            video_choice = rng.choice(_video_specs()[:2])  # bitrate or crf

        # Encourage overlapping manipulations
        chosen = [c for c in [trim_choice, scale_choice, audio_choice, video_choice] if c]
        if len(chosen) < 2 and rng.random() < plan.overlap_prob:
            # Force one more dimension
            if not scale_choice:
                scale_choice = rng.choice(_scale_specs())
            elif not audio_choice:
                audio_choice = VariantSpec("noaudio", "remove_audio", {})

        recipes.append(
            {
                "trim": trim_choice,
                "scale": scale_choice,
                "audio": audio_choice,
                "video": video_choice,
            }
        )

    return recipes


def create_random_variants(
    key: str,
    src_path: Path,
    dest_dir: Path,
    *,
    plan: RandomPlan,
    ffmpeg_mode: str = "cpu",
    ffmpeg_threads: Optional[int] = None,
    flat_variants: bool = False,
) -> List[Path]:
    """Create randomized overlapping variants for a key."""

    variant_dir = dest_dir if flat_variants else dest_dir / key
    variant_dir.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []

    recipes = _plan_random_variants(key, plan)
    for idx, recipe in enumerate(recipes, start=1):
        out_name = f"{key}_rand{idx:02d}.mp4"
        dest_path = variant_dir / out_name
        if dest_path.exists():
            outputs.append(dest_path)
            continue
        try:
            _render_combo_variant(
                src_path,
                dest_path,
                trim=recipe.get("trim"),
                scale=recipe.get("scale"),
                audio=recipe.get("audio"),
                video=recipe.get("video"),
                mode=ffmpeg_mode,
                threads=ffmpeg_threads,
            )
            outputs.append(dest_path)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to create randomized variant %s: %s", dest_path, exc)

    return outputs


def parse_trim(arg: str) -> TrimSpec:
    """Parse a CLI trim spec of the form `name:start:duration` or `start:duration`."""

    parts = arg.split(":")
    if len(parts) == 2:
        name = f"clip_{parts[0]}_{parts[1]}"
        start, duration = parts
    elif len(parts) == 3:
        name, start, duration = parts
    else:
        raise argparse.ArgumentTypeError("Trim spec must be start:duration or name:start:duration")
    try:
        start_f = float(start)
        duration_f = float(duration)
    except ValueError as exc:  # pragma: no cover
        raise argparse.ArgumentTypeError("Start and duration must be numbers") from exc
    return TrimSpec(name=name, start=start_f, duration=duration_f)


def build_truth_manifest(output_dir: Path) -> Dict[str, Dict[str, List[str]]]:
    """Scan output_dir and build a truth manifest mapping keys to files."""

    output_dir = output_dir.resolve()
    originals_dir = output_dir / "original"
    variants_dir = output_dir / "variants"
    manifest: Dict[str, Dict[str, List[str]]] = {}

    if originals_dir.exists():
        for original in sorted(originals_dir.glob("*.*")):
            key = original.stem
            variant_files: List[Path] = []
            # Per-key directory layout
            per_key_dir = variants_dir / key
            if per_key_dir.exists():
                variant_files.extend(sorted(p for p in per_key_dir.glob("*.*") if p.is_file()))
            # Flat layout fallback
            variant_files.extend(sorted(p for p in variants_dir.glob(f"{key}_*.*") if p.is_file()))

            manifest[key] = {
                "original": str(original.relative_to(output_dir)),
                "variants": [str(p.relative_to(output_dir)) for p in variant_files],
            }
    return manifest


def write_truth_manifest(manifest: Dict[str, Dict[str, List[str]]], output_dir: Path, truth_file: Path | None = None) -> Path:
    """Write the manifest JSON to truth_file (default output_dir/truth.json)."""

    truth_path = truth_file or output_dir / "truth.json"
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "dataset_root": str(output_dir.resolve()),
        "keys": manifest,
    }
    truth_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote truth manifest to %s", truth_path)
    return truth_path


def write_mapping_files(keys: List[str], id_map: Dict[str, str], mapping_path: Path, id_map_path: Path) -> None:
    """Write mapping.txt (keys) and id_map.json to disk."""

    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    id_map_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text("\n".join(keys) + "\n", encoding="utf-8")
    id_map_path.write_text(json.dumps(id_map, indent=2), encoding="utf-8")
    logger.info("Wrote mapping file to %s and id map to %s", mapping_path, id_map_path)


def prepare_keys_from_urls(
    urls: List[str],
    *,
    num_masters: int,
    seed: Optional[int],
    shuffle_urls: bool,
) -> tuple[List[str], Dict[str, str]]:
    """Select num_masters URLs and build key->URL mapping with master-video-N names."""

    if not urls:
        raise ValueError("No URLs provided")
    urls_copy = list(urls)
    rng = random.Random(seed)
    if shuffle_urls:
        rng.shuffle(urls_copy)
    selected = urls_copy[:num_masters]
    keys = [f"master-video-{i+1}" for i in range(len(selected))]
    id_map = {key: url for key, url in zip(keys, selected)}
    return keys, id_map


def generate_dataset(
    keys: Iterable[str],
    id_map: Dict[str, str],
    output_dir: Path,
    *,
    skip_download: bool = False,
    extra_trims: Sequence[TrimSpec] | None = None,
    write_manifest: bool = True,
    truth_file: Path | None = None,
    flat_variants: bool = False,
    random_plan: Optional[RandomPlan] = None,
    workers: int = 1,
    ffmpeg_mode: str = "cpu",
    ffmpeg_threads: Optional[int] = None,
    max_mem_gb: Optional[float] = None,
    progress: ProgressTracker | None = None,
) -> Dict[str, Dict[str, List[str]]]:
    """
    Download originals (unless skip_download) and create variants.
    Returns the manifest mapping for the generated dataset.
    """

    originals_dir = output_dir / "original"
    variants_dir = output_dir / "variants"
    originals_dir.mkdir(parents=True, exist_ok=True)
    variants_dir.mkdir(parents=True, exist_ok=True)

    def _process_key(item: Tuple[int, str]) -> None:
        worker_id, key = item

        def set_stage(stage: str) -> None:
            if progress and hasattr(progress, "set_worker_stage"):
                try:
                    progress.set_worker_stage(worker_id, key, stage)
                except Exception:
                    pass

        youtube_id = id_map.get(key)
        if not youtube_id:
            logger.warning("No YouTube source for key %s; skipping", key)
            return
        if progress:
            progress.on_start(key)
            set_stage("start")
        try:
            if skip_download:
                existing = [p for p in originals_dir.glob(f"{key}.*") if p.stat().st_size > 0]
                if not existing:
                    logger.error("skip_download set but no original found for %s", key)
                    return
                src_path = existing[0]
            else:
                src_path = download_video(youtube_id, originals_dir, key)
                if progress:
                    progress.on_download()
                    set_stage("downloaded")
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to obtain video for %s: %s", key, exc)
            if progress:
                progress.on_error()
                set_stage("error-download")
            return

        try:
            det = create_variants(
                key,
                src_path,
                variants_dir,
                extra_trims=extra_trims,
                ffmpeg_mode=ffmpeg_mode,
                ffmpeg_threads=ffmpeg_threads,
                flat_variants=flat_variants,
            )
            if random_plan:
                rand = create_random_variants(
                    key,
                    src_path,
                    variants_dir,
                    plan=random_plan,
                    ffmpeg_mode=ffmpeg_mode,
                    ffmpeg_threads=ffmpeg_threads,
                    flat_variants=flat_variants,
                )
            else:
                rand = []
            if progress:
                progress.on_variants(len(det), len(rand))
                set_stage("done")
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to create variants for %s: %s", key, exc)
            if progress:
                progress.on_error()
                set_stage("error-variants")
            return

    worker_limit = max(1, workers)
    if max_mem_gb is not None:
        mem_cap = max(1, int(max_mem_gb // 2) or 1)
        worker_limit = min(worker_limit, mem_cap)
        logger.info("Memory cap %.1f GB applied; workers limited to %d", max_mem_gb, worker_limit)

    keys_list = list(keys)
    if progress:
        progress.set_total(len(keys_list))
    work_items = []
    for idx, key in enumerate(keys_list, start=1):
        wid = ((idx - 1) % worker_limit) + 1
        work_items.append((wid, key))

    if worker_limit == 1 or len(keys_list) <= 1:
        for item in work_items:
            _process_key(item)
    else:
        logger.info("Processing with %d worker threads (mode=%s)", worker_limit, ffmpeg_mode)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_limit) as executor:
            list(executor.map(_process_key, work_items))

    manifest = build_truth_manifest(output_dir)
    if write_manifest:
        write_truth_manifest(manifest, output_dir, truth_file=truth_file)
    return manifest


class _Formatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


_EPILOG = """
Examples:
  # Pick 20 masters from a URLs file, deterministic order/seed
  vdt -u urls.txt -M 20 -S 123 -o data -y

  # Same but shuffle URLs before selecting, with 4 workers and CUDA/NVENC
  vdt -u urls.txt -M 20 -S 123 --shuffle-urls -J 4 -g cuda -y

  # Heavier randomized variants: 3-6 variants per master, overlap bias 0.7
  vdt -u urls.txt -M 20 -S 123 -R 3 -X 6 -p 0.7 -o data -y

  # Flat layout, ffmpeg threads capped, live dashboard
  vdt -u urls.txt -M 10 -f -T 4 -d -y

  # Reuse downloaded masters, add extra trim, disable random variants
  vdt -m mapping.txt -i id_map.json -s -r clipA:10:30 --no-random -y
  
    # Auto-discover 100 random YouTube videos (seeded) and generate variants
    vdt -Z 100 -S 42 -R 3 -X 6 -p 0.65 -J 4 -g cuda -d -y
"""


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate video datasets with deterministic and randomized variants",
        formatter_class=_Formatter,
        epilog=_EPILOG,
    )
    parser.add_argument("-m", "--mapping-file", type=Path, help="Text file with one key per line")
    parser.add_argument("-i", "--id-map", type=Path, help="JSON map of key -> YouTube ID/URL")
    parser.add_argument("-u", "--urls-file", type=Path, help="File with YouTube URLs to auto-create mapping/id map")
    parser.add_argument("-M", "--num-masters", type=int, default=3, help="Number of master videos to download (urls-file mode)")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("data"), help="Directory for dataset output")
    parser.add_argument("-s", "--skip-download", action="store_true", help="Reuse existing originals and skip yt-dlp")
    parser.add_argument(
        "-t",
        "--truth-file",
        type=Path,
        default=None,
        help="Optional path for the truth manifest (defaults to output-dir/truth.json)",
    )
    parser.add_argument(
        "-r",
        "--trim",
        action="append",
        type=parse_trim,
        default=[],
        metavar="SPEC",
        help="Additional trim spec (start:duration or name:start:duration). Can be repeated.",
    )
    parser.add_argument("-S", "--seed", type=int, default=None, help="Seed for randomized variants and URL shuffling")
    parser.add_argument("-R", "--min-random-variants", type=int, default=2, help="Minimum randomized variants per master")
    parser.add_argument("-X", "--max-random-variants", type=int, default=5, help="Maximum randomized variants per master")
    parser.add_argument(
        "-p",
        "--overlap-prob",
        type=float,
        default=0.65,
        help="Probability of forcing overlapping manipulations in randomized variants",
    )
    parser.add_argument("-f", "--flat-layout", action="store_true", help="Place all variants in a single variants/ directory")
    parser.add_argument("-w", "--mapping-out", type=Path, default=None, help="Where to write generated mapping file (urls mode)")
    parser.add_argument("-j", "--id-map-out", type=Path, default=None, help="Where to write generated id map (urls mode)")
    parser.add_argument("-g", "--mode", choices=["cpu", "cuda"], default="cpu", help="Acceleration mode (cpu or cuda)")
    parser.add_argument("-J", "--workers", type=int, default=os.cpu_count() or 4, help="Concurrent download/variant workers")
    parser.add_argument("-T", "--ffmpeg-threads", type=int, default=None, help="Threads per ffmpeg process (None=ffmpeg default)")
    parser.add_argument("-U", "--max-mem-gb", type=float, default=None, help="Optional memory cap to limit workers")
    parser.add_argument("-L", "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging verbosity")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Plan only; do not invoke yt-dlp or ffmpeg")
    parser.add_argument("-y", "--confirm", action="store_true", help="Confirm execution when running non-dry-run")
    parser.add_argument("--shuffle-urls", action="store_true", help="Shuffle URLs before selecting num-masters")
    parser.add_argument("--no-random", action="store_true", help="Disable randomized overlapping variants")
    parser.add_argument("-d", "--ui", action="store_true", help="Show live terminal dashboard (termdash) during processing")
    parser.add_argument(
        "-Z",
        "--auto-urls",
        type=int,
        default=0,
        help="Auto-discover N YouTube URLs via yt-dlp search (seeded, no URLs file needed)",
    )
    return parser.parse_args(argv)


def _require_mapping_sources(args: argparse.Namespace) -> None:
    if not args.mapping_file and not args.urls_file and args.auto_urls <= 0:
        raise SystemExit("Provide --mapping-file/--id-map, --urls-file, or --auto-urls")
    if args.urls_file and args.num_masters < 1:
        raise SystemExit("--num-masters must be >= 1")
    if args.max_random_variants < args.min_random_variants:
        raise SystemExit("--max-random-variants must be >= --min-random-variants")


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    if args.auto_urls > 0 and args.num_masters != args.auto_urls:
        logger.info("Overriding --num-masters (%d) to match --auto-urls (%d)", args.num_masters, args.auto_urls)
        args.num_masters = args.auto_urls

    if args.dry_run:
        logger.info("Dry-run: no downloads or transforms will be executed")
        logger.info("Planned output directory: %s", args.output_dir.resolve())
        return

    if not args.confirm:
        logger.error("Refusing to run without --confirm/-y (safety toggle)")
        return

    _require_mapping_sources(args)

    try:
        ensure_yt_dlp()
        ensure_ffmpeg()
    except RuntimeError as exc:
        logger.error(str(exc))
        return

    # Prepare mapping/id map
    mapping_file = args.mapping_file
    id_map_file = args.id_map
    keys: List[str]
    id_map: Dict[str, str]

    if args.auto_urls > 0:
        auto_urls = discover_random_urls(args.auto_urls, seed=args.seed)
        keys, id_map = prepare_keys_from_urls(
            auto_urls,
            num_masters=len(auto_urls),
            seed=args.seed,
            shuffle_urls=args.shuffle_urls,
        )
        mapping_file = args.mapping_out or (args.output_dir / "mapping.txt")
        id_map_file = args.id_map_out or (args.output_dir / "id_map.json")
        write_mapping_files(keys, id_map, mapping_file, id_map_file)
    elif args.urls_file:
        urls = parse_urls_file(args.urls_file)
        keys, id_map = prepare_keys_from_urls(
            urls,
            num_masters=args.num_masters,
            seed=args.seed,
            shuffle_urls=args.shuffle_urls,
        )
        mapping_file = args.mapping_out or (args.output_dir / "mapping.txt")
        id_map_file = args.id_map_out or (args.output_dir / "id_map.json")
        write_mapping_files(keys, id_map, mapping_file, id_map_file)
    else:
        if not mapping_file or not id_map_file:
            logger.error("Both --mapping-file and --id-map are required when not using --urls-file or --auto-urls")
            return
        try:
            keys = load_keys(mapping_file)
        except Exception as exc:
            logger.error("Failed to load mapping file %s: %s", mapping_file, exc)
            return
        try:
            id_map = load_id_map(id_map_file)
        except Exception as exc:
            logger.error("Failed to load ID map %s: %s", id_map_file, exc)
            return

    random_plan = None
    if not args.no_random:
        random_plan = RandomPlan(
            seed=args.seed,
            min_variants=args.min_random_variants,
            max_variants=args.max_random_variants,
            overlap_prob=args.overlap_prob,
        )

    tracker: ProgressTracker | None = None
    board_cm = nullcontext()
    if args.ui:
        tracker, board_cm = _maybe_start_ui(len(keys), args.workers)

    with board_cm:
        manifest = generate_dataset(
            keys,
            id_map,
            args.output_dir,
            skip_download=args.skip_download,
            extra_trims=args.trim,
            write_manifest=True,
            truth_file=args.truth_file,
            flat_variants=args.flat_layout,
            random_plan=random_plan,
            workers=args.workers,
            ffmpeg_mode=args.mode,
            ffmpeg_threads=args.ffmpeg_threads,
            max_mem_gb=args.max_mem_gb,
            progress=tracker,
        )

    logger.info(
        "Wrote truth manifest for %d masters to %s",
        len(manifest),
        args.truth_file or args.output_dir / "truth.json",
    )


if __name__ == "__main__":
    main()
