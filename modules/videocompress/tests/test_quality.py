"""Tests for videocompress.quality frame-aligned metric calculation and caveats."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from videocompress.contracts import VideoAsset, VideoStream
from videocompress.quality import (
    QualityMetrics,
    calculate_quality_metrics,
    parse_ffmpeg_metric_output,
)
from videocompress.sampling import SampleWindow


SAMPLE_FFMPEG_METRIC_STDERR = """
[Parsed_ssim_0 @ 0000021a8b1c4b00] SSIM Y:0.975412 (16.098712) U:0.988401 (19.356213) V:0.987145 (18.905412) All:0.981512 (17.334512)
[Parsed_psnr_1 @ 0000021a8b1c5500] PSNR y:41.251234 u:44.512341 v:43.912341 average:42.123412 min:37.512341 max:inf
"""


def test_parse_ffmpeg_metric_output():
    """Verify regex extraction of SSIM and PSNR values from FFmpeg stderr."""
    metrics = parse_ffmpeg_metric_output(SAMPLE_FFMPEG_METRIC_STDERR)
    assert metrics.ssim_y == pytest.approx(0.975412, rel=1e-5)
    assert metrics.ssim_u == pytest.approx(0.988401, rel=1e-5)
    assert metrics.ssim_v == pytest.approx(0.987145, rel=1e-5)
    assert metrics.ssim_all == pytest.approx(0.981512, rel=1e-5)

    assert metrics.psnr_y == pytest.approx(41.251234, rel=1e-5)
    assert metrics.psnr_u == pytest.approx(44.512341, rel=1e-5)
    assert metrics.psnr_v == pytest.approx(43.912341, rel=1e-5)
    assert metrics.psnr_all == pytest.approx(42.123412, rel=1e-5)

    # Verification of caveats
    assert any("fidelity to existing file" in c for c in metrics.caveats)
    assert any("Bitrate confidence does not imply perceptual quality" in c for c in metrics.caveats)


def test_quality_measurement_source_immutability(tmp_path: Path):
    """Quality metric measurement must assert source file immutability."""
    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"source_content" * 100)
    sample_file = tmp_path / "sample.mp4"
    sample_file.write_bytes(b"sample_content" * 100)

    window = SampleWindow(window_index=0, start_seconds=0.0, duration_seconds=5.0)

    # Simulate source modification during subprocess
    def mutating_run(*args, **kwargs):
        source_file.write_bytes(b"mutated!")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", SAMPLE_FFMPEG_METRIC_STDERR.encode("utf-8"))
        return mock_proc

    from videocompress.adapters.ffmpeg import SourceMutationError

    with patch("subprocess.Popen", side_effect=mutating_run):
        with pytest.raises(SourceMutationError, match="CRITICAL SAFETY VIOLATION"):
            calculate_quality_metrics(
                source_path=source_file,
                sample_path=sample_file,
                window=window,
            )


def test_real_quality_metrics_on_synthetic_clip(tmp_path: Path):
    """Execute real FFmpeg filtergraph on synthetic clips to verify frame alignment and metric scoring."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not found on PATH")

    source_file = tmp_path / "ref.mp4"
    sample_file = tmp_path / "dist.mp4"

    # Generate 1-second reference clip (testsrc)
    cmd_ref = [
        "ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
        "-c:v", "libx264", "-crf", "18", "-an", str(source_file),
    ]
    subprocess.run(cmd_ref, check=True, capture_output=True)

    # Generate slightly compressed clip (crf 28)
    cmd_dist = [
        "ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
        "-c:v", "libx264", "-crf", "28", "-an", str(sample_file),
    ]
    subprocess.run(cmd_dist, check=True, capture_output=True)

    source_stat_before = source_file.stat()

    window = SampleWindow(window_index=0, start_seconds=0.0, duration_seconds=1.0)
    qm = calculate_quality_metrics(
        source_path=source_file,
        sample_path=sample_file,
        window=window,
    )

    # Check metrics
    assert qm.ssim_all is not None
    assert 0.80 <= qm.ssim_all <= 1.0
    assert qm.psnr_all is not None
    assert qm.psnr_all > 30.0

    # Verify source immutability
    source_stat_after = source_file.stat()
    assert source_stat_after.st_mtime_ns == source_stat_before.st_mtime_ns
    assert source_stat_after.st_size == source_stat_before.st_size
