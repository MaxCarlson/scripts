#!/usr/bin/env python3
"""
Randomized media dataset builder for supervised vdedup evaluation.

This script:
  1. Uses yt-dlp to discover YouTube videos for a list of search queries.
  2. Randomly samples a requested number of sources (deterministic via --seed).
  3. Downloads each source clip (capped by --max-size) as an MP4.
  4. Produces several manipulated variants (downscales, upscales, random subsets).
  5. Emits a JSON manifest describing ground-truth duplicate groupings plus negatives.

Example:
    python modules/vdedup/tests/generate_media_dataset.py \\
        --sources 5 \\
        --queries "open source short film,nature timelapse,b-roll drone" \\
        --seed 1337

Requirements:
    * yt-dlp (recent build with --print-json support)
    * ffmpeg / ffprobe

All network activity happens via yt-dlp. Ensure you respect YouTube's TOS and only
download videos you are licensed to use for testing.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


DATASET_ROOT = Path(__file__).resolve().parent / "media_dataset"
DEFAULT_QUERIES = [
    "creative commons short film",
    "nature timelapse 4k",
    "drone b-roll city",
    "ocean wildlife documentary clip",
    "sports highlight creative commons",
]
DEFAULT_MAX_SIZE = 40 * 1024 * 1024  # 40 MiB
DEFAULT_SEED_BANK = [101, 303, 707, 1009, 1337]
MIN_DURATION = 20  # seconds
MAX_DURATION = 900
NEGATIVE_SYNTH_DURATION = 15


def _ensure_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool '{name}' not found on PATH.")


def _run(cmd: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    display = " ".join(cmd)
    print(">", display)
    return subprocess.run(cmd, check=True, capture_output=capture, text=True)


def _flatten_entries(data: Dict) -> Iterable[Dict]:
    if not isinstance(data, dict):
        return []
    if data.get("_type") == "playlist":
        for entry in data.get("entries", []) or []:
            if entry:
                yield entry
    else:
        yield data


def _discover_candidates(queries: Sequence[str], per_query: int) -> List[Dict]:
    candidates: List[Dict] = []
    for query in queries:
        spec = f"ytsearch{per_query}:{query}"
        proc = _run(
            [
                "yt-dlp",
                spec,
                "--skip-download",
                "--print-json",
                "--no-warnings",
            ],
            capture=True,
        )
        for line in proc.stdout.splitlines():
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            for entry in _flatten_entries(data):
                vid = entry.get("id")
                duration = entry.get("duration")
                if not vid or duration is None:
                    continue
                if duration < MIN_DURATION or duration > MAX_DURATION:
                    continue
                url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
                candidates.append(
                    {
                        "id": vid,
                        "title": entry.get("title") or vid,
                        "duration": float(duration),
                        "url": url,
                    }
                )
    return candidates


def _select_sources(candidates: Sequence[Dict], count: int, seed: int) -> List[Dict]:
    uniq: Dict[str, Dict] = {}
    for cand in candidates:
        uniq.setdefault(cand["id"], cand)
    pool = list(uniq.values())
    rng = random.Random(seed)
    rng.shuffle(pool)
    return pool[: min(count, len(pool))]


def _download_video(url: str, dest: Path, max_size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".downloading.mp4")
    _run(
        [
            "yt-dlp",
            "--no-playlist",
            "--max-filesize",
            str(max_size),
            "-f",
            "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]",
            "-o",
            str(tmp),
            url,
        ]
    )
    tmp.rename(dest)


def _probe_duration(path: Path) -> float:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _ffmpeg_transcode(src: Path, dest: Path, args: Sequence[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(src), *args, str(dest)])


def _downscale_variant(src: Path, dest: Path, rng: random.Random) -> Dict:
    target = rng.choice([720, 540, 480, 360])
    crf = rng.randint(24, 32)
    _ffmpeg_transcode(
        src,
        dest,
        [
            "-vf",
            f"scale=-2:{target}",
            "-c:v",
            "libx264",
            "-preset",
            "faster",
            "-crf",
            str(crf),
            "-c:a",
            "aac",
            "-b:a",
            "96k",
        ],
    )
    return {"path": str(dest), "role": f"downscale_{target}p"}


def _upscale_variant(src: Path, dest: Path, rng: random.Random) -> Dict:
    target = rng.choice([1440, 2160])
    crf = rng.randint(20, 26)
    _ffmpeg_transcode(
        src,
        dest,
        [
            "-vf",
            f"scale=-2:{target}",
            "-c:v",
            "libx265",
            "-preset",
            "slow",
            "-crf",
            str(crf),
            "-c:a",
            "copy",
        ],
    )
    return {"path": str(dest), "role": f"upscale_{target}p"}


def _subset_variant(src: Path, dest: Path, rng: random.Random, index: int) -> Dict:
    duration = _probe_duration(src)
    if duration <= 6:
        clip_len = max(3.0, duration * 0.8)
        start = 0.0
    else:
        clip_len = rng.uniform(5.0, min(30.0, duration * 0.35))
        slack = max(duration - clip_len - 1.0, 0.0)
        start = rng.uniform(0.0, slack)
    clip_len = min(clip_len, duration - start)
    args = [
        "-ss",
        f"{start:.3f}",
        "-i",
        str(src),
        "-t",
        f"{clip_len:.3f}",
        "-c",
        "copy",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", *args, str(dest)])
    return {"path": str(dest), "role": f"subset_{index}", "start": start, "duration": clip_len}


def _generate_variants(src: Path, group_dir: Path, rng: random.Random, subset_count: int) -> List[Dict]:
    outputs: List[Dict] = []
    master = group_dir / f"{src.stem}_master.mp4"
    if master != src:
        shutil.copy2(src, master)
    outputs.append({"path": str(master), "role": "master"})
    outputs.append(
        _downscale_variant(
            master,
            group_dir / f"{src.stem}_downscale.mp4",
            rng,
        )
    )
    outputs.append(
        _upscale_variant(
            master,
            group_dir / f"{src.stem}_upscale.mp4",
            rng,
        )
    )
    for idx in range(subset_count):
        outputs.append(
            _subset_variant(
                master,
                group_dir / f"{src.stem}_subset_{idx}.mp4",
                rng,
                idx,
            )
        )
    return outputs


def _generate_negative_clip(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880",
            "-shortest",
            "-t",
            str(NEGATIVE_SYNTH_DURATION),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(dest),
        ]
    )


def build_dataset(
    output_dir: Path,
    *,
    queries: Sequence[str],
    per_query: int,
    sources: int,
    subset_count: int,
    seed: int,
    max_size: int,
    force: bool,
) -> Dict[str, object]:
    rng = random.Random(seed)
    manifest = {"seed": seed, "queries": list(queries), "groups": [], "negatives": []}
    candidates = _discover_candidates(queries, per_query)
    if not candidates:
        raise RuntimeError("No candidate videos were discovered. Try different queries.")
    selected = _select_sources(candidates, sources, seed)
    if not selected:
        raise RuntimeError("Unable to select any sources from discovered candidates.")

    for meta in selected:
        group_id = meta["id"]
        group_dir = output_dir / group_id
        group_dir.mkdir(parents=True, exist_ok=True)
        master_path = group_dir / f"{group_id}_raw.mp4"
        if not master_path.exists() or force:
            _download_video(meta["url"], master_path, max_size)
        variants = _generate_variants(master_path, group_dir, rng, subset_count)
        manifest["groups"].append(
            {
                "id": group_id,
                "title": meta["title"],
                "duration": meta["duration"],
                "members": variants,
            }
        )

    neg_dir = output_dir / "negatives"
    neg_dir.mkdir(parents=True, exist_ok=True)
    neg_path = neg_dir / "synthetic_grid.mp4"
    if not neg_path.exists() or force:
        _generate_negative_clip(neg_path)
    manifest["negatives"].append({"path": str(neg_path), "description": "Synthetic color grid"})

    manifest_path = output_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDataset manifest written to {manifest_path}")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Randomized video dataset generator for vdedup.")
    parser.add_argument("--output", type=Path, default=DATASET_ROOT, help="Directory to store dataset (default: tests/media_dataset)")
    parser.add_argument(
        "--queries",
        type=str,
        default=",".join(DEFAULT_QUERIES),
        help="Comma-separated search queries for yt-dlp (default: built-in mix)",
    )
    parser.add_argument("--per-query", type=int, default=6, help="Search results to consider per query (default: 6)")
    parser.add_argument("--sources", type=int, default=4, help="Number of unique source videos to download (default: 4)")
    parser.add_argument("--subset-count", type=int, default=2, help="Subset clips per source (default: 2)")
    parser.add_argument("--seed", type=int, default=1234, help="Seed controlling random sampling (default: 1234)")
    parser.add_argument(
        "--seed-list",
        type=str,
        default="default",
        help="Comma-separated seeds, path to a seed file, or 'default' to use the built-in bank",
    )
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE, help="Maximum download size per source (bytes)")
    parser.add_argument("--force", action="store_true", default=False, help="Rebuild clips even if they already exist")
    return parser.parse_args()


def _parse_seed_list(arg: str) -> List[int]:
    if not arg:
        return []
    lowered = arg.strip().lower()
    if lowered == "default":
        return list(DEFAULT_SEED_BANK)
    if lowered == "none":
        return []
    path = Path(arg)
    seeds: List[int] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                seeds.append(int(line))
            except ValueError:
                continue
        return seeds
    for part in arg.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            seeds.append(int(part))
        except ValueError:
            continue
    return seeds


def main() -> None:
    args = parse_args()
    output_root = args.output.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    for tool in ("yt-dlp", "ffmpeg", "ffprobe"):
        _ensure_binary(tool)
    query_list = [q.strip() for q in args.queries.split(",") if q.strip()]
    if not query_list:
        query_list = DEFAULT_QUERIES
    seed_list = _parse_seed_list(args.seed_list)
    if not seed_list:
        seed_list = [args.seed]
    for seed in seed_list:
        seed_dir = output_root / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Building dataset for seed {seed} into {seed_dir} ===")
        build_dataset(
            seed_dir,
            queries=query_list,
            per_query=max(1, args.per_query),
            sources=max(1, args.sources),
            subset_count=max(1, args.subset_count),
            seed=seed,
            max_size=args.max_size,
            force=args.force,
        )


if __name__ == "__main__":
    main()
