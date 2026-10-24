"""FFmpeg subprocess adapter for safe sample trial encoding and measurement."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videocompress.contracts import VideoAsset, VideoStream
from videocompress.probe import probe_video_file
from videocompress.recipes import VideoRecipe
from videocompress.sampling import SampleWindow


class SourceMutationError(RuntimeError):
    """Raised when source media is modified during encoding (critical safety violation)."""


class FFmpegTimeoutError(TimeoutError):
    """Raised when FFmpeg subprocess exceeds its time budget."""


class SampleValidationError(RuntimeError):
    """Raised when encoded sample fails output integrity or codec validation."""


class FFmpegExecutionError(RuntimeError):
    """Raised when FFmpeg returns a non-zero exit code."""


@dataclass(frozen=True, slots=True)
class SampleEncodeResult:
    """Detailed measurement result from an encoded temporal sample clip."""

    sample_path: Path
    source_path: Path
    recipe_id: str
    window_index: int
    window_start: float
    window_duration: float
    actual_duration: float
    sample_file_bytes: int
    sample_video_bytes: int
    sample_video_bps: int
    encode_seconds: float
    fps_throughput: float
    encoder: str
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_path": str(self.sample_path),
            "source_path": str(self.source_path),
            "recipe_id": self.recipe_id,
            "window_index": self.window_index,
            "window_start": self.window_start,
            "window_duration": self.window_duration,
            "actual_duration": self.actual_duration,
            "sample_file_bytes": self.sample_file_bytes,
            "sample_video_bytes": self.sample_video_bytes,
            "sample_video_bps": self.sample_video_bps,
            "encode_seconds": round(self.encode_seconds, 3),
            "fps_throughput": round(self.fps_throughput, 2),
            "encoder": self.encoder,
        }


class FFmpegAdapter:
    """Manages safe, bounded FFmpeg sample encoding processes."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = ffmpeg_bin

    def _kill_process_tree(self, pid: int) -> None:
        """Kill Windows process tree cleanly to prevent orphan processes."""
        if sys.platform == "win32":
            # Graceful termination attempt first
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                check=False,
            )
            time.sleep(0.5)
            # Forced termination
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.kill(pid, 15)  # SIGTERM
                time.sleep(0.5)
                os.kill(pid, 9)   # SIGKILL
            except OSError:
                pass

    def encode_sample_clip(
        self,
        source_path: Path,
        recipe: VideoRecipe,
        window: SampleWindow,
        scratch_dir: Path,
        timeout_seconds: float = 60.0,
    ) -> SampleEncodeResult:
        """Encode a bounded temporal sample clip into isolated scratch space.

        Guarantees:
        - Source immutability verification (mtime_ns and file size).
        - Scratch path isolation check (never adjacent to or inside source directory).
        - Bounded duration and timeout enforcement with process tree cancellation.
        - Output validation via FFprobe.
        """
        source_path = source_path.resolve()
        scratch_dir = scratch_dir.resolve()

        # 1. Scratch isolation check
        try:
            source_parent = source_path.parent.resolve()
            if scratch_dir == source_parent or scratch_dir.is_relative_to(source_parent):
                raise ValueError(
                    f"Scratch directory must be isolated from source media. Scratch: {scratch_dir}, Source: {source_parent}"
                )
        except AttributeError:
            # Fallback for Python < 3.9 if is_relative_to not present, but we are on Python 3.12
            if str(scratch_dir).startswith(str(source_parent)):
                raise ValueError("Scratch directory must be isolated from source media.")

        scratch_dir.mkdir(parents=True, exist_ok=True)
        sample_path = scratch_dir / f"sample_w{window.window_index}_{recipe.recipe_id}.mp4"

        # 2. Record initial source stat fingerprint
        initial_stat = source_path.stat()
        initial_fingerprint = (initial_stat.st_mtime_ns, initial_stat.st_size)

        # 3. Build FFmpeg command line
        cmd = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-nostats",
            "-nostdin",
            "-y",
            "-ss",
            f"{window.start_seconds:.3f}",
            "-t",
            f"{window.duration_seconds:.3f}",
            "-i",
            str(source_path),
            "-c:v",
            recipe.encoder,
            "-preset",
            recipe.preset,
        ]

        if recipe.rate_control_mode == "cq":
            # NVENC rate control options
            if "nvenc" in recipe.encoder:
                cmd.extend(["-rc", "vbr", "-cq:v", str(recipe.rate_control_value)])
            else:
                cmd.extend(["-crf", str(recipe.rate_control_value)])

        if recipe.pix_fmt:
            cmd.extend(["-pix_fmt", recipe.pix_fmt])

        extra_args = getattr(recipe, "extra_ffmpeg_args", ())
        if extra_args:
            cmd.extend(extra_args)

        # Strip audio (-an) to measure exact video elementary stream bitrate
        cmd.extend(["-an", str(sample_path)])

        start_time = time.perf_counter()
        proc = None
        stdout_str = ""
        stderr_str = ""

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout_seconds)
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            if proc and proc.pid:
                self._kill_process_tree(proc.pid)
            raise FFmpegTimeoutError(
                f"FFmpeg sample encode timed out after {timeout_seconds}s for {source_path.name} window {window.window_index}"
            ) from exc
        finally:
            # 4. CRITICAL: Source immutability check
            current_stat = source_path.stat()
            current_fingerprint = (current_stat.st_mtime_ns, current_stat.st_size)
            if current_fingerprint != initial_fingerprint:
                raise SourceMutationError(
                    f"CRITICAL SAFETY VIOLATION: Source media '{source_path}' was modified during encode! "
                    f"Initial: {initial_fingerprint}, Current: {current_fingerprint}"
                )

        elapsed_seconds = max(0.001, time.perf_counter() - start_time)

        if proc.returncode != 0:
            raise FFmpegExecutionError(
                f"FFmpeg sample encode failed with return code {proc.returncode}: {stderr_str[-1000:]}"
            )

        # 5. Output validation
        if not sample_path.exists() or sample_path.stat().st_size == 0:
            raise SampleValidationError(
                f"Output sample file does not exist or is empty: {sample_path}"
            )

        sample_bytes = sample_path.stat().st_size

        # Probe the encoded sample to measure duration, bitrate, and verify codec
        try:
            probed_asset = probe_video_file(sample_path)
        except Exception as exc:
            raise SampleValidationError(
                f"Failed to probe encoded sample {sample_path}: {exc}"
            ) from exc

        probed_vstreams = [s for s in probed_asset.streams if s.stream_type == "video"]
        if not probed_vstreams:
            raise SampleValidationError(
                f"Encoded sample {sample_path} contains no video stream."
            )

        sample_vstream = probed_vstreams[0]
        # Verify codec match (e.g. av1, hevc, h264)
        if sample_vstream.codec_name and recipe.codec not in sample_vstream.codec_name:
            raise SampleValidationError(
                f"Target codec mismatch: expected {recipe.codec}, got {sample_vstream.codec_name}"
            )

        actual_duration = probed_asset.duration_seconds
        if actual_duration <= 0:
            actual_duration = window.duration_seconds

        # Video bitrate from probe or elementary container bytes
        if sample_vstream.bit_rate_bps and sample_vstream.bit_rate_bps > 0:
            sample_video_bps = sample_vstream.bit_rate_bps
            sample_video_bytes = int(sample_video_bps * actual_duration / 8.0)
        else:
            # With -an, sample_bytes is video elementary stream + minimal mp4/mkv container header (~1-2KB)
            sample_video_bytes = max(0, sample_bytes - 2048)
            sample_video_bps = int(sample_video_bytes * 8.0 / actual_duration) if actual_duration > 0 else 0

        fps = 24.0
        if sample_vstream.fps_num and sample_vstream.fps_den:
            fps = sample_vstream.fps_num / sample_vstream.fps_den

        fps_throughput = (actual_duration * fps) / elapsed_seconds

        return SampleEncodeResult(
            sample_path=sample_path,
            source_path=source_path,
            recipe_id=recipe.recipe_id,
            window_index=window.window_index,
            window_start=window.start_seconds,
            window_duration=window.duration_seconds,
            actual_duration=round(actual_duration, 3),
            sample_file_bytes=sample_bytes,
            sample_video_bytes=sample_video_bytes,
            sample_video_bps=sample_video_bps,
            encode_seconds=elapsed_seconds,
            fps_throughput=fps_throughput,
            encoder=recipe.encoder,
            stdout=stdout_str,
            stderr=stderr_str,
        )
