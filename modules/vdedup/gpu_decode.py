from __future__ import annotations

import io
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional


LOGGER = logging.getLogger(__name__)
LAST_DECODE_BACKEND: Optional[str] = None


@dataclass(slots=True)
class DecodeResult:
    path: Path
    requested_timestamps: List[float]
    frames: List[Any]
    backend: Optional[str]
    attempted_gpu: bool
    fallback_used: bool
    gpu_error: Optional[str] = None
    cpu_error: Optional[str] = None
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return bool(self.frames)


def _import_torch() -> Any:
    import torch  # noqa: PLC0415

    return torch


def _import_pynvcodec() -> Any:
    import PyNvVideoCodec as nvc  # noqa: PLC0415

    return nvc


def _decode_gpu(path: Path, timestamps: List[float], device_id: int) -> List[Any]:
    torch = _import_torch()
    nvc = _import_pynvcodec()
    decoder = nvc.SimpleDecoder(str(path), gpu_id=device_id)
    frames: List[Any] = []
    for timestamp in timestamps:
        frame: Any
        if hasattr(decoder, "seek_to_time"):
            decoder.seek_to_time(float(timestamp))
            frame = decoder.decode()
        elif hasattr(decoder, "seek"):
            decoder.seek(float(timestamp))
            frame = decoder.decode()
        elif hasattr(decoder, "get_frame_at_time"):
            frame = decoder.get_frame_at_time(float(timestamp))
        else:
            frame = next(iter(decoder))
        if frame is None:
            continue
        if hasattr(frame, "__dlpack__"):
            frames.append(torch.from_dlpack(frame))
        else:
            frames.append(frame)
    return frames


def _decode_cpu_frame(path: Path, timestamp: float) -> Any:
    try:
        from PIL import Image  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except Exception:
        return None

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    with Image.open(io.BytesIO(raw)) as img:
        return np.asarray(img.convert("RGB"), dtype=np.uint8)


def _decode_cpu(path: Path, timestamps: List[float]) -> List[Any]:
    frames: List[Any] = []
    errors: List[str] = []
    for timestamp in timestamps:
        try:
            frame = _decode_cpu_frame(path, timestamp)
            if frame is not None:
                frames.append(frame)
            else:
                errors.append(f"{timestamp:.3f}s: CPU frame decode unavailable")
        except Exception as exc:
            errors.append(f"{timestamp:.3f}s: {exc}")
            LOGGER.debug("CPU frame decode failed for %s at %.3fs", path, timestamp, exc_info=True)
    if not frames and errors:
        raise RuntimeError("; ".join(errors[:3]))
    return frames


def decode_frames_at_timestamps(
    path: Path,
    timestamps: List[float],
    device_id: int = 0,
    use_gpu: bool = True,
) -> DecodeResult:
    """
    Decode frames at the given timestamps and return a structured DecodeResult.

    GPU decode is attempted first when requested and dependencies are available. CPU fallback is isolated
    per-video: unrecoverable failures are returned as DecodeResult.error instead of aborting a scan.
    """
    global LAST_DECODE_BACKEND
    LAST_DECODE_BACKEND = None
    normalized_path = Path(path)
    requested_timestamps = [float(timestamp) for timestamp in timestamps]
    if not requested_timestamps:
        return DecodeResult(
            path=normalized_path,
            requested_timestamps=[],
            frames=[],
            backend=None,
            attempted_gpu=bool(use_gpu),
            fallback_used=False,
            error="no timestamps requested",
        )

    if use_gpu:
        try:
            frames = _decode_gpu(normalized_path, requested_timestamps, device_id)
            if frames:
                LAST_DECODE_BACKEND = "gpu_pynvcodec"
                return DecodeResult(
                    path=normalized_path,
                    requested_timestamps=requested_timestamps,
                    frames=frames,
                    backend="gpu_pynvcodec",
                    attempted_gpu=True,
                    fallback_used=False,
                )
            gpu_error = "GPU decoder returned zero frames"
        except Exception as exc:
            gpu_error = str(exc)
            LOGGER.debug("GPU decode failed for %s; falling back to CPU ffmpeg", path, exc_info=True)
    else:
        gpu_error = None

    try:
        frames = _decode_cpu(normalized_path, requested_timestamps)
        if frames:
            LAST_DECODE_BACKEND = "cpu_ffmpeg"
            return DecodeResult(
                path=normalized_path,
                requested_timestamps=requested_timestamps,
                frames=frames,
                backend="cpu_ffmpeg",
                attempted_gpu=bool(use_gpu),
                fallback_used=bool(use_gpu),
                gpu_error=gpu_error,
            )
        cpu_error = "CPU decoder returned zero frames"
    except Exception as exc:
        cpu_error = str(exc)
        LOGGER.debug("CPU decode failed for %s", path, exc_info=True)
    LAST_DECODE_BACKEND = None
    return DecodeResult(
        path=normalized_path,
        requested_timestamps=requested_timestamps,
        frames=[],
        backend=None,
        attempted_gpu=bool(use_gpu),
        fallback_used=bool(use_gpu),
        gpu_error=gpu_error,
        cpu_error=cpu_error,
        error=cpu_error or gpu_error or "decode failed",
    )
