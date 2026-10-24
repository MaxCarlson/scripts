"""Visual preview generator: split-screen side-by-side clips and preview manifests."""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
import shutil
import subprocess
from typing import Any, Sequence

from videocompress.adapters.ffmpeg import FFmpegAdapter, SourceMutationError
from videocompress.contracts import VideoAsset, VideoRecipe
from videocompress.quality import QualityMetrics, calculate_quality_metrics
from videocompress.sampling import SampleWindow, generate_sample_windows
from videocompress.workspace import VideoWorkspace


@dataclass(frozen=True, slots=True)
class PreviewClipRecord:
    """Record of a rendered preview clip."""

    clip_id: str
    source_id: str
    recipe_id: str
    window_index: int
    start_seconds: float
    duration_seconds: float
    preview_mode: str  # split or standalone
    clip_path: str
    clip_bytes: int
    metrics: QualityMetrics | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "source_id": self.source_id,
            "recipe_id": self.recipe_id,
            "window_index": self.window_index,
            "start_seconds": round(self.start_seconds, 3),
            "duration_seconds": round(self.duration_seconds, 3),
            "preview_mode": self.preview_mode,
            "clip_path": str(self.clip_path),
            "clip_bytes": self.clip_bytes,
            "metrics": self.metrics.to_dict() if self.metrics else None,
        }


@dataclass(frozen=True, slots=True)
class PreviewManifest:
    """Inspection manifest describing generated preview clips for external review."""

    manifest_id: str
    target_path: str
    clips: list[PreviewClipRecord]
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    instructions: str = (
        "Open preview clips in any external video player (e.g. VLC, mpv, Windows Media Player) "
        "to visually verify compression quality, detail preservation, and freedom from artifacts."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "target_path": self.target_path,
            "created_at": self.created_at,
            "instructions": self.instructions,
            "clips": [c.to_dict() for c in self.clips],
        }


def generate_preview_clips(
    asset: VideoAsset,
    canonical_path: str,
    recipe: VideoRecipe,
    workspace: VideoWorkspace,
    num_clips: int = 3,
    clip_duration_seconds: float = 5.0,
    preview_mode: str = "split",
    ffmpeg_bin: str = "ffmpeg",
) -> PreviewManifest:
    """Generate visual preview clips and manifest in workspace/previews/.

    Guarantees:
    - Bounded duration (short clips only).
    - Source immutability check before and after execution.
    - Zero modification of source media.
    """
    source_p = Path(canonical_path).resolve()
    if not source_p.exists():
        raise FileNotFoundError(f"Source file not found: {source_p}")

    initial_stat = source_p.stat()
    initial_fingerprint = (initial_stat.st_mtime_ns, initial_stat.st_size)

    timestamp = int(datetime.datetime.now().timestamp())
    manifest_id = f"prev_{asset.source_id[:8]}_{recipe.recipe_id}_{timestamp}"
    preview_dir = workspace.previews_dir / manifest_id
    preview_dir.mkdir(parents=True, exist_ok=True)

    adapter = FFmpegAdapter(ffmpeg_bin=ffmpeg_bin)
    schedule = "s5" if num_clips > 3 else "s3"
    windows = generate_sample_windows(
        duration_seconds=asset.duration_seconds,
        schedule=schedule,
        window_duration_seconds=clip_duration_seconds,
    )

    selected_windows = windows[:num_clips]
    clip_records: list[PreviewClipRecord] = []

    for w in selected_windows:
        scratch_dir = workspace.root / "scratch" / f"prev_tmp_{w.window_index}_{timestamp}"
        sample_res = adapter.encode_sample_clip(
            source_path=source_p,
            recipe=recipe,
            window=w,
            scratch_dir=scratch_dir,
        )

        out_clip_name = f"preview_w{w.window_index}_{preview_mode}.mp4"
        out_clip_path = preview_dir / out_clip_name

        if preview_mode == "split":
            # Side-by-side split screen: left = source, right = encoded sample
            # [0:v] is source slice, [1:v] is sample clip
            filter_split = (
                "[0:v]settb=AVTB,setpts=PTS-STARTPTS,crop=iw/2:ih:0:0[left];"
                "[1:v]settb=AVTB,setpts=PTS-STARTPTS,crop=iw/2:ih:iw/2:0[right];"
                "[left][right]hstack[v]"
            )
            split_cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-nostats",
                "-nostdin",
                "-y",
                "-ss",
                f"{w.start_seconds:.3f}",
                "-t",
                f"{w.duration_seconds:.3f}",
                "-i",
                str(source_p),
                "-i",
                str(sample_res.sample_path),
                "-filter_complex",
                filter_split,
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-an",
                str(out_clip_path),
            ]
            res = subprocess.run(split_cmd, capture_output=True, text=True)
            if res.returncode != 0:
                # If hstack failed, copy sample clip directly
                shutil.copy2(sample_res.sample_path, out_clip_path)
        else:
            shutil.copy2(sample_res.sample_path, out_clip_path)

        # Quality scoring
        qm = calculate_quality_metrics(
            source_path=source_p,
            sample_path=sample_res.sample_path,
            window=w,
            ffmpeg_bin=ffmpeg_bin,
        )

        # Cleanup intermediate scratch clip
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir, ignore_errors=True)

        clip_bytes = out_clip_path.stat().st_size if out_clip_path.exists() else 0
        clip_records.append(
            PreviewClipRecord(
                clip_id=f"{manifest_id}_w{w.window_index}",
                source_id=asset.source_id,
                recipe_id=recipe.recipe_id,
                window_index=w.window_index,
                start_seconds=w.start_seconds,
                duration_seconds=w.duration_seconds,
                preview_mode=preview_mode,
                clip_path=str(out_clip_path),
                clip_bytes=clip_bytes,
                metrics=qm,
            )
        )

    # Verify source immutability
    final_stat = source_p.stat()
    final_fingerprint = (final_stat.st_mtime_ns, final_stat.st_size)
    if final_fingerprint != initial_fingerprint:
        raise SourceMutationError(
            f"CRITICAL SAFETY VIOLATION: Source media '{source_p}' was modified during preview generation!"
        )

    manifest = PreviewManifest(
        manifest_id=manifest_id,
        target_path=str(source_p),
        clips=clip_records,
    )

    manifest_file = preview_dir / "preview_manifest.json"
    manifest_file.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")

    return manifest
