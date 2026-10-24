"""Frame-aligned quality assessment (SSIM, PSNR, VMAF) with metric and confidence contracts."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from videocompress.adapters.ffmpeg import FFmpegAdapter, FFmpegTimeoutError, SourceMutationError
from videocompress.sampling import SampleWindow


DEFAULT_QUALITY_CAVEATS: tuple[str, ...] = (
    "Full-reference metrics compare encoded sample against lossy user reference. "
    "Metrics measure fidelity to existing file, not absolute perceptual perfection.",
    "Bitrate confidence does not imply perceptual quality preservation across unseen content.",
    "Automatic perceptual metrics do not guarantee freedom from visible compression artifacts.",
)


@dataclass(frozen=True, slots=True)
class QualityMetrics:
    """Frame-aligned objective quality measurement results with explicit caveats."""

    ssim_y: float | None = None
    ssim_u: float | None = None
    ssim_v: float | None = None
    ssim_all: float | None = None
    psnr_y: float | None = None
    psnr_u: float | None = None
    psnr_v: float | None = None
    psnr_all: float | None = None
    vmaf_mean: float | None = None
    vmaf_min: float | None = None
    vmaf_p10: float | None = None
    metric_model: str = "ssim_psnr"
    frames_evaluated: int = 0
    evaluated_duration: float = 0.0
    caveats: tuple[str, ...] = field(default_factory=lambda: DEFAULT_QUALITY_CAVEATS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ssim_y": round(self.ssim_y, 4) if self.ssim_y is not None else None,
            "ssim_u": round(self.ssim_u, 4) if self.ssim_u is not None else None,
            "ssim_v": round(self.ssim_v, 4) if self.ssim_v is not None else None,
            "ssim_all": round(self.ssim_all, 4) if self.ssim_all is not None else None,
            "psnr_y": round(self.psnr_y, 2) if self.psnr_y is not None else None,
            "psnr_u": round(self.psnr_u, 2) if self.psnr_u is not None else None,
            "psnr_v": round(self.psnr_v, 2) if self.psnr_v is not None else None,
            "psnr_all": round(self.psnr_all, 2) if self.psnr_all is not None else None,
            "vmaf_mean": round(self.vmaf_mean, 2) if self.vmaf_mean is not None else None,
            "vmaf_min": round(self.vmaf_min, 2) if self.vmaf_min is not None else None,
            "vmaf_p10": round(self.vmaf_p10, 2) if self.vmaf_p10 is not None else None,
            "metric_model": self.metric_model,
            "frames_evaluated": self.frames_evaluated,
            "evaluated_duration": round(self.evaluated_duration, 3),
            "caveats": list(self.caveats),
        }


def parse_ffmpeg_metric_output(stderr_text: str) -> QualityMetrics:
    """Parse SSIM, PSNR, and VMAF outputs from FFmpeg stderr logging."""
    ssim_y = None
    ssim_u = None
    ssim_v = None
    ssim_all = None

    # Matches SSIM Y:0.975412 (16.098712) U:0.988401 (19.356213) V:0.987145 (18.905412) All:0.981512 (17.334512)
    # or RGB variant SSIM R:1.000000 (inf) G:1.000000 (inf) B:1.000000 (inf) All:1.000000 (inf)
    ssim_match = re.search(
        r"SSIM\s+[YyRr]:([\d.]+)\s+\([^)]+\)\s+[UuGg]:([\d.]+)\s+\([^)]+\)\s+[VvBb]:([\d.]+)\s+\([^)]+\)\s+All:([\d.]+)",
        stderr_text,
    )
    if ssim_match:
        try:
            ssim_y = float(ssim_match.group(1))
            ssim_u = float(ssim_match.group(2))
            ssim_v = float(ssim_match.group(3))
            ssim_all = float(ssim_match.group(4))
        except (ValueError, TypeError):
            pass
    elif "All:" in stderr_text:
        all_match = re.search(r"All:([\d.]+)", stderr_text)
        if all_match:
            try:
                ssim_all = float(all_match.group(1))
            except (ValueError, TypeError):
                pass

    psnr_y = None
    psnr_u = None
    psnr_v = None
    psnr_all = None

    # Matches PSNR y:41.251234 u:44.512341 v:43.912341 average:42.123412 or average:inf
    psnr_match = re.search(
        r"PSNR\s+[YyRr]:([\d.]+|inf)\s+[UuGg]:([\d.]+|inf)\s+[VvBb]:([\d.]+|inf)\s+average:([\d.]+|inf)",
        stderr_text,
    )
    if psnr_match:
        try:
            val_y = psnr_match.group(1)
            val_u = psnr_match.group(2)
            val_v = psnr_match.group(3)
            val_all = psnr_match.group(4)
            psnr_y = 100.0 if val_y == "inf" else float(val_y)
            psnr_u = 100.0 if val_u == "inf" else float(val_u)
            psnr_v = 100.0 if val_v == "inf" else float(val_v)
            psnr_all = 100.0 if val_all == "inf" else float(val_all)
        except (ValueError, TypeError):
            pass
    elif "average:" in stderr_text:
        avg_match = re.search(r"average:([\d.]+|inf)", stderr_text)
        if avg_match:
            val_avg = avg_match.group(1)
            psnr_all = 100.0 if val_avg == "inf" else float(val_avg)

    # Optional VMAF score
    vmaf_mean = None
    vmaf_match = re.search(r"VMAF score:\s*([\d.]+)", stderr_text)
    if vmaf_match:
        try:
            vmaf_mean = float(vmaf_match.group(1))
        except (ValueError, TypeError):
            pass

    metric_model = "libvmaf_v1" if vmaf_mean is not None else "ssim_psnr"

    return QualityMetrics(
        ssim_y=ssim_y,
        ssim_u=ssim_u,
        ssim_v=ssim_v,
        ssim_all=ssim_all,
        psnr_y=psnr_y,
        psnr_u=psnr_u,
        psnr_v=psnr_v,
        psnr_all=psnr_all,
        vmaf_mean=vmaf_mean,
        metric_model=metric_model,
        caveats=DEFAULT_QUALITY_CAVEATS,
    )


def calculate_quality_metrics(
    source_path: Path | str,
    sample_path: Path | str,
    window: SampleWindow,
    include_vmaf: bool = False,
    timeout_seconds: float = 60.0,
    ffmpeg_bin: str = "ffmpeg",
) -> QualityMetrics:
    """Execute frame-aligned quality assessment between source slice and encoded sample.

    Guarantees:
    - Frame alignment with PTS reset (`settb=AVTB,setpts=PTS-STARTPTS`).
    - Source immutability verification before/after execution.
    - Zero modification of source media.
    """
    source_p = Path(source_path).resolve()
    sample_p = Path(sample_path).resolve()

    if not source_p.exists():
        raise FileNotFoundError(f"Source file not found: {source_p}")
    if not sample_p.exists() or sample_p.stat().st_size == 0:
        raise FileNotFoundError(f"Sample clip file not found or empty: {sample_p}")

    initial_stat = source_p.stat()
    initial_fingerprint = (initial_stat.st_mtime_ns, initial_stat.st_size)

    # Frame-aligned filtergraph with PTS alignment, format normalization, and split
    # [0:v] is source slice, [1:v] is encoded sample clip
    num_metrics = 2 if not include_vmaf else 3
    filter_parts = [
        f"[0:v]settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p,split={num_metrics}" + "".join(f"[r{i}]" for i in range(num_metrics)),
        f"[1:v]settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p,split={num_metrics}" + "".join(f"[d{i}]" for i in range(num_metrics)),
        "[d0][r0]ssim",
        "[d1][r1]psnr",
    ]

    if include_vmaf:
        filter_parts.append("[d2][r2]libvmaf")

    filter_graph = ";".join(filter_parts)

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostats",
        "-nostdin",
        "-y",
        "-ss",
        f"{window.start_seconds:.3f}",
        "-t",
        f"{window.duration_seconds:.3f}",
        "-i",
        str(source_p),
        "-i",
        str(sample_p),
        "-filter_complex",
        filter_graph,
        "-f",
        "null",
        "-",
    ]

    adapter = FFmpegAdapter(ffmpeg_bin=ffmpeg_bin)
    proc = None
    stderr_str = ""

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr_bytes = proc.communicate(timeout=timeout_seconds)
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        if proc and proc.pid:
            adapter._kill_process_tree(proc.pid)
        raise FFmpegTimeoutError(
            f"Quality measurement timed out after {timeout_seconds}s for {source_p.name}"
        ) from exc
    finally:
        current_stat = source_p.stat()
        current_fingerprint = (current_stat.st_mtime_ns, current_stat.st_size)
        if current_fingerprint != initial_fingerprint:
            raise SourceMutationError(
                f"CRITICAL SAFETY VIOLATION: Source media '{source_p}' was modified during quality measurement! "
                f"Initial: {initial_fingerprint}, Current: {current_fingerprint}"
            )

    qm = parse_ffmpeg_metric_output(stderr_str)
    # Return enriched metrics with duration
    return QualityMetrics(
        ssim_y=qm.ssim_y,
        ssim_u=qm.ssim_u,
        ssim_v=qm.ssim_v,
        ssim_all=qm.ssim_all,
        psnr_y=qm.psnr_y,
        psnr_u=qm.psnr_u,
        psnr_v=qm.psnr_v,
        psnr_all=qm.psnr_all,
        vmaf_mean=qm.vmaf_mean,
        metric_model=qm.metric_model,
        frames_evaluated=qm.frames_evaluated,
        evaluated_duration=window.duration_seconds,
        caveats=DEFAULT_QUALITY_CAVEATS,
    )
