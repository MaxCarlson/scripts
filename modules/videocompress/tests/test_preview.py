"""Tests for videocompress.preview clip rendering and manifest generation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from videocompress.contracts import VideoAsset, VideoStream
from videocompress.preview import (
    PreviewClipRecord,
    PreviewManifest,
    generate_preview_clips,
)
from videocompress.recipes import get_recipe
from videocompress.workspace import resolve_workspace


def test_preview_manifest_serialization(tmp_path: Path):
    """Verify PreviewManifest dataclass and dictionary serialization."""
    clip = PreviewClipRecord(
        clip_id="clip_0",
        source_id="src_1",
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        start_seconds=10.0,
        duration_seconds=5.0,
        preview_mode="split",
        clip_path="preview_0.mp4",
        clip_bytes=1_200_000,
        metrics=None,
    )
    manifest = PreviewManifest(
        manifest_id="manifest_123",
        target_path="video.mp4",
        clips=[clip],
        instructions="Open clips in external player for visual review.",
    )

    data = manifest.to_dict()
    assert data["manifest_id"] == "manifest_123"
    assert len(data["clips"]) == 1
    assert data["clips"][0]["preview_mode"] == "split"


def test_real_preview_clip_generation(tmp_path: Path):
    """Execute preview generation on synthetic clip and verify preview files and manifest."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not found on PATH")

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    source_file = media_dir / "preview_src.mp4"

    # Generate 3-second reference clip
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24",
        "-c:v", "libx264", "-crf", "20", "-an", str(source_file),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    ws = resolve_workspace(media_dir)
    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=320, height=240, bit_rate_bps=1_000_000)
    asset = VideoAsset(
        source_id="prev-asset",
        relative_path="preview_src.mp4",
        file_bytes=source_file.stat().st_size,
        container_format="mp4",
        duration_seconds=3.0,
        streams=(vstream,),
    )

    recipe = get_recipe("h264_nvenc_cq24")
    source_stat_before = source_file.stat()

    manifest = generate_preview_clips(
        asset=asset,
        canonical_path=str(source_file),
        recipe=recipe,
        workspace=ws,
        num_clips=1,
        clip_duration_seconds=1.0,
        preview_mode="split",
    )

    # 1. Manifest file must exist on disk
    assert len(manifest.clips) == 1
    clip_rec = manifest.clips[0]
    clip_file = Path(clip_rec.clip_path)
    assert clip_file.exists()
    assert clip_file.stat().st_size > 0

    # 2. Manifest JSON file must exist in preview dir
    manifest_json_file = clip_file.parent / "preview_manifest.json"
    assert manifest_json_file.exists()

    # 3. Source file must be completely untouched
    source_stat_after = source_file.stat()
    assert source_stat_after.st_mtime_ns == source_stat_before.st_mtime_ns
    assert source_stat_after.st_size == source_stat_before.st_size
