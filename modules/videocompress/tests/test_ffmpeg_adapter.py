"""Tests for videocompress.adapters.ffmpeg safe subprocess execution and safety contracts."""

import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from videocompress.adapters.ffmpeg import (
    FFmpegAdapter,
    FFmpegTimeoutError,
    SampleEncodeResult,
    SampleValidationError,
    SourceMutationError,
)
from videocompress.recipes import get_recipe
from videocompress.sampling import SampleWindow


def test_scratch_isolation_and_source_immutability_contract(tmp_path: Path):
    """FFmpegAdapter must enforce scratch isolation and verify source immutability."""
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    source_file = media_dir / "test_source.mp4"
    source_file.write_bytes(b"initial_unmodified_media_bytes" * 100)

    scratch_dir = tmp_path / "workspace" / "scratch" / "trial_01"
    scratch_dir.mkdir(parents=True)

    adapter = FFmpegAdapter()

    # Verify that scratch path cannot be inside media_dir
    with pytest.raises(ValueError, match="Scratch directory must be isolated from source"):
        adapter.encode_sample_clip(
            source_path=source_file,
            recipe=get_recipe("av1_nvenc_cq30"),
            window=SampleWindow(0, 0.0, 5.0),
            scratch_dir=media_dir / "unsafe_scratch",
        )


def test_source_mutation_detection_raises_error(tmp_path: Path):
    """If source file size or mtime changes during execution, SourceMutationError MUST be raised."""
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    source_file = media_dir / "mutating_source.mp4"
    source_file.write_bytes(b"initial_bytes" * 50)

    scratch_dir = tmp_path / "scratch" / "trial_02"
    scratch_dir.mkdir(parents=True)

    adapter = FFmpegAdapter()

    # Simulate mutation of source during subprocess run
    def mutating_run(*args, **kwargs):
        # Mutate source file
        source_file.write_bytes(b"corrupted_mutated_bytes_disaster!")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        return mock_proc

    with patch("subprocess.Popen", side_effect=mutating_run):
        with pytest.raises(SourceMutationError, match="CRITICAL SAFETY VIOLATION"):
            adapter.encode_sample_clip(
                source_path=source_file,
                recipe=get_recipe("av1_nvenc_cq30"),
                window=SampleWindow(0, 0.0, 5.0),
                scratch_dir=scratch_dir,
            )


def test_ffmpeg_timeout_and_process_cleanup(tmp_path: Path):
    """FFmpeg subprocess exceeding timeout must be killed with process tree cleanup."""
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    source_file = media_dir / "source.mp4"
    source_file.write_bytes(b"source_bytes" * 50)

    scratch_dir = tmp_path / "scratch" / "trial_03"
    scratch_dir.mkdir(parents=True)

    adapter = FFmpegAdapter()

    # We mock a hung process
    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=0.1)
    mock_proc.poll.return_value = None

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch.object(adapter, "_kill_process_tree") as mock_kill:
            with pytest.raises(FFmpegTimeoutError, match="timed out"):
                adapter.encode_sample_clip(
                    source_path=source_file,
                    recipe=get_recipe("av1_nvenc_cq30"),
                    window=SampleWindow(0, 0.0, 5.0),
                    scratch_dir=scratch_dir,
                    timeout_seconds=0.1,
                )
            mock_kill.assert_called_once_with(99999)


def test_sample_validation_rejects_empty_output(tmp_path: Path):
    """Output sample that is 0 bytes or missing must raise SampleValidationError."""
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    source_file = media_dir / "source.mp4"
    source_file.write_bytes(b"source_bytes" * 50)

    scratch_dir = tmp_path / "scratch" / "trial_04"
    scratch_dir.mkdir(parents=True)

    adapter = FFmpegAdapter()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    with patch("subprocess.Popen", return_value=mock_proc):
        # We did not create sample.mp4 in scratch_dir
        with pytest.raises(SampleValidationError, match="Output sample file does not exist or is empty"):
            adapter.encode_sample_clip(
                source_path=source_file,
                recipe=get_recipe("av1_nvenc_cq30"),
                window=SampleWindow(0, 0.0, 5.0),
                scratch_dir=scratch_dir,
            )


def test_real_ffmpeg_sample_encode_execution(tmp_path: Path):
    """Execute real FFmpeg encode on a synthetic source clip and verify sample measurements."""
    import shutil
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not found on PATH")

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    source_file = media_dir / "synthetic.mp4"

    # Generate a tiny 2-second synthetic video clip
    gen_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=320x240:rate=24",
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p4",
        "-cq:v",
        "28",
        "-an",
        str(source_file),
    ]
    res = subprocess.run(gen_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Fallback to libx264 if nvenc unavailable in synthetic generator
        gen_cmd[10] = "libx264"
        res = subprocess.run(gen_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            pytest.skip(f"Failed to generate synthetic source clip: {res.stderr}")

    source_stat_before = source_file.stat()

    scratch_dir = tmp_path / "scratch" / "trial_real"
    scratch_dir.mkdir(parents=True)

    adapter = FFmpegAdapter()
    recipe = get_recipe("h264_nvenc_cq24")
    window = SampleWindow(window_index=0, start_seconds=0.0, duration_seconds=1.0)

    result = adapter.encode_sample_clip(
        source_path=source_file,
        recipe=recipe,
        window=window,
        scratch_dir=scratch_dir,
    )

    # 1. Output sample must exist and have non-zero bytes
    assert result.sample_path.exists()
    assert result.sample_file_bytes > 0
    assert result.actual_duration > 0
    assert result.sample_video_bps > 0
    assert result.fps_throughput > 0
    assert result.encoder == "h264_nvenc"

    # 2. Source file must be completely untouched (source immutability verified)
    source_stat_after = source_file.stat()
    assert source_stat_after.st_mtime_ns == source_stat_before.st_mtime_ns
    assert source_stat_after.st_size == source_stat_before.st_size

