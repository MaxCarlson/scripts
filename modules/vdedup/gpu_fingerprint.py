from __future__ import annotations

import math
from pathlib import Path
from typing import Any, List, Optional, Tuple

from vdedup.gpu_sampling import is_edge_timestamp, select_frame_timestamps
from vdedup.models import FrameSignature, VideoSignature


PHASH_RESIZE_SIZE = 32
PHASH_LOW_FREQ_SIZE = 8
PHASH_LUMA_WEIGHTS = (0.299, 0.587, 0.114)
PHASH_SPEC = (
    "pHash64: RGB to luma with Y=0.299R+0.587G+0.114B; resize to 32x32; "
    "orthonormal DCT-II; use top-left 8x8 coefficients including DC; threshold by "
    "the lower median of those 64 coefficients; pack bits row-major, most-significant bit first. "
    "Torch CPU/CUDA tensors use the same implementation; the pure-PIL fallback is threshold-compatible "
    "but may not be bit-identical on all frames because resize kernels differ."
)


def _import_torch() -> Any:
    import torch  # noqa: PLC0415

    return torch


def _is_torch_tensor(value: Any) -> bool:
    return value.__class__.__module__.split(".", 1)[0] == "torch"


def _frame_to_pil(frame: Any) -> Any:
    from PIL import Image  # noqa: PLC0415

    if hasattr(Image, "Image") and isinstance(frame, Image.Image):
        return frame.convert("RGB")
    if _is_torch_tensor(frame):
        tensor = frame.detach()
        if tensor.ndim == 3 and tensor.shape[0] in {1, 3, 4}:
            tensor = tensor.permute(1, 2, 0)
        data = tensor.to("cpu").tolist()
    else:
        data = frame.tolist() if hasattr(frame, "tolist") else frame
    if not data:
        return Image.new("RGB", (1, 1))
    if isinstance(data[0][0], (int, float)):
        pixels = data
        height = len(pixels)
        width = len(pixels[0])
        flat = [int(max(0, min(255, round(value * 255 if value <= 1 else value)))) for row in pixels for value in row]
        image = Image.new("L", (width, height))
        image.putdata(flat)
        return image.convert("RGB")
    if (
        len(data) in {1, 3, 4}
        and data
        and data[0]
        and data[0][0]
        and isinstance(data[0][0][0], (int, float))
    ):
        channels = data
        height = len(channels[0])
        width = len(channels[0][0])
        hwc_data = []
        for y in range(height):
            row = []
            for x in range(width):
                row.append([channels[c][y][x] for c in range(min(3, len(channels)))])
            hwc_data.append(row)
        data = hwc_data
    height = len(data)
    width = len(data[0])
    flat_rgb = []
    for row in data:
        for pixel in row:
            channels = list(pixel)
            if max(channels[:3]) <= 1:
                channels = [value * 255 for value in channels]
            flat_rgb.append(tuple(int(max(0, min(255, round(value)))) for value in channels[:3]))
    image = Image.new("RGB", (width, height))
    image.putdata(flat_rgb)
    return image


def _pack_bits(bits: List[bool]) -> int:
    value = 0
    for bit in bits[:64]:
        value = (value << 1) | int(bool(bit))
    return int(value)


def _image_flat_data(image: Any) -> List[Any]:
    getter = getattr(image, "get_flattened_data", None)
    if getter is not None:
        return list(getter())
    return list(image.getdata())


def _torch_normalize_batch(frames: List[Any]) -> Any:
    torch = _import_torch()
    tensors = []
    for frame in frames:
        tensor = frame if _is_torch_tensor(frame) else torch.as_tensor(frame)
        if tensor.ndim != 3:
            raise ValueError("Expected frame tensors/arrays with 3 dimensions.")
        if tensor.shape[0] in {1, 3, 4}:
            tensor = tensor[:3, :, :]
        elif tensor.shape[-1] in {1, 3, 4}:
            tensor = tensor[..., :3].permute(2, 0, 1)
        else:
            raise ValueError("Expected RGB frame data in CHW or HWC layout.")
        tensor = tensor.to(dtype=torch.float32)
        if float(tensor.max().detach().to("cpu")) > 1.0:
            tensor = tensor / 255.0
        tensors.append(tensor)
    return torch.stack(tensors, dim=0)


def _dct_matrix(size: int, device: Any, dtype: Any) -> Any:
    torch = _import_torch()
    matrix = torch.empty((size, size), device=device, dtype=dtype)
    factor = math.pi / (2.0 * size)
    scale0 = math.sqrt(1.0 / size)
    scale = math.sqrt(2.0 / size)
    for k in range(size):
        for n in range(size):
            coeff = scale0 if k == 0 else scale
            matrix[k, n] = coeff * math.cos((2 * n + 1) * k * factor)
    return matrix


def _compute_phash64_torch(frames: List[Any]) -> List[int]:
    torch = _import_torch()
    functional = torch.nn.functional
    batch = _torch_normalize_batch(frames)
    weights = torch.tensor(PHASH_LUMA_WEIGHTS, device=batch.device, dtype=batch.dtype).view(1, 3, 1, 1)
    luma = (batch * weights).sum(dim=1, keepdim=True)
    resized = functional.interpolate(
        luma, size=(PHASH_RESIZE_SIZE, PHASH_RESIZE_SIZE), mode="bilinear", align_corners=False
    ).squeeze(1)
    dct = _dct_matrix(PHASH_RESIZE_SIZE, resized.device, resized.dtype)
    coeff = dct @ resized @ dct.t()
    low_freq = coeff[:, :PHASH_LOW_FREQ_SIZE, :PHASH_LOW_FREQ_SIZE].reshape(coeff.shape[0], 64)
    medians = low_freq.median(dim=1).values.unsqueeze(1)
    bits = (low_freq > medians).to("cpu").tolist()
    return [_pack_bits(row) for row in bits]


def _dct_matrix_list(size: int) -> List[List[float]]:
    matrix = []
    factor = math.pi / (2.0 * size)
    for k in range(size):
        row = []
        scale = math.sqrt(1.0 / size) if k == 0 else math.sqrt(2.0 / size)
        for n in range(size):
            row.append(scale * math.cos((2 * n + 1) * k * factor))
        matrix.append(row)
    return matrix


def _compute_phash64_pil(frame: Any) -> int:
    from PIL import Image  # noqa: PLC0415

    image = _frame_to_pil(frame).resize((PHASH_RESIZE_SIZE, PHASH_RESIZE_SIZE), resample=Image.Resampling.BILINEAR)
    pixels = _image_flat_data(image)
    luma = [
        [
            (
                (PHASH_LUMA_WEIGHTS[0] * pixels[(y * PHASH_RESIZE_SIZE) + x][0])
                + (PHASH_LUMA_WEIGHTS[1] * pixels[(y * PHASH_RESIZE_SIZE) + x][1])
                + (PHASH_LUMA_WEIGHTS[2] * pixels[(y * PHASH_RESIZE_SIZE) + x][2])
            )
            / 255.0
            for x in range(PHASH_RESIZE_SIZE)
        ]
        for y in range(PHASH_RESIZE_SIZE)
    ]
    dct = _dct_matrix_list(PHASH_RESIZE_SIZE)
    temp = [
        [sum(dct[k][n] * luma[n][x] for n in range(PHASH_RESIZE_SIZE)) for x in range(PHASH_RESIZE_SIZE)]
        for k in range(PHASH_RESIZE_SIZE)
    ]
    coeff = [
        [sum(temp[y][n] * dct[k][n] for n in range(PHASH_RESIZE_SIZE)) for k in range(PHASH_LOW_FREQ_SIZE)]
        for y in range(PHASH_LOW_FREQ_SIZE)
    ]
    low_freq = [value for row in coeff for value in row]
    median = sorted(low_freq)[(len(low_freq) - 1) // 2]
    return _pack_bits([value > median for value in low_freq])


def _compute_phash64_cpu(frames: List[Any]) -> List[int]:
    if any(_is_torch_tensor(frame) for frame in frames):
        try:
            return _compute_phash64_torch(frames)
        except Exception:
            pass
    return [_compute_phash64_pil(frame) for frame in frames]


def compute_phash64_batch(frames: List[Any], use_gpu: bool = True) -> List[int]:
    if not frames:
        return []
    if use_gpu:
        try:
            return _compute_phash64_torch(frames)
        except Exception:
            pass
    return _compute_phash64_cpu(frames)


def _quality_from_luma_values(values: List[float]) -> Tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    mean_luma = sum(values) / len(values)
    counts = [0] * 32
    for value in values:
        idx = min(31, max(0, int(value * 32)))
        counts[idx] += 1
    entropy = 0.0
    total = float(len(values))
    for count in counts:
        if count:
            probability = count / total
            entropy -= probability * math.log2(probability)
    variance = sum((value - mean_luma) ** 2 for value in values) / len(values)
    return entropy, mean_luma, math.sqrt(variance)


def compute_frame_quality(frames: List[Any], use_gpu: bool = True) -> List[Tuple[float, float]]:
    if not frames:
        return []
    qualities: List[Tuple[float, float]] = []
    for frame in frames:
        image = _frame_to_pil(frame).convert("L").resize((64, 64))
        values = [pixel / 255.0 for pixel in _image_flat_data(image)]
        entropy, mean_luma, _std_luma = _quality_from_luma_values(values)
        qualities.append((float(entropy), float(mean_luma)))
    return qualities


def _compute_frame_std_luma(frame: Any) -> float:
    image = _frame_to_pil(frame).convert("L").resize((64, 64))
    values = [pixel / 255.0 for pixel in _image_flat_data(image)]
    _entropy, _mean_luma, std_luma = _quality_from_luma_values(values)
    return float(std_luma)


def is_valid_for_matching(entropy: float, mean_luma: float) -> bool:
    return mean_luma >= (4.0 / 255.0) and mean_luma <= (251.0 / 255.0) and entropy >= 1.0


def _video_id(path: Path) -> str:
    return str(Path(path))


def _duration_seconds(path: Path) -> Optional[float]:
    try:
        from vdedup.probe import run_ffprobe_json  # noqa: PLC0415

        data = run_ffprobe_json(Path(path))
        if not data:
            return None
        value = data.get("format", {}).get("duration")
        return float(value) if value is not None else None
    except Exception:
        return None


def extract_video_signature(
    path: Path,
    profile: str = "balanced",
    device_id: int = 0,
    use_gpu: bool = True,
    duration_seconds: Optional[float] = None,
    fps: Optional[float] = None,
    total_frames: Optional[int] = None,
) -> Optional[VideoSignature]:
    del fps, total_frames
    duration = duration_seconds if duration_seconds is not None else _duration_seconds(Path(path))
    if duration is None or duration <= 0:
        return None
    timestamps = select_frame_timestamps(duration, profile=profile)
    if not timestamps:
        return None

    from vdedup import gpu_decode  # noqa: PLC0415

    decode_result = gpu_decode.decode_frames_at_timestamps(Path(path), timestamps, device_id=device_id, use_gpu=use_gpu)
    if not decode_result.succeeded:
        return None

    frames = decode_result.frames
    actual_timestamps = decode_result.requested_timestamps[: len(frames)]
    phashes = compute_phash64_batch(frames, use_gpu=use_gpu)
    qualities = compute_frame_quality(frames, use_gpu=use_gpu)
    video_id = _video_id(Path(path))
    frame_signatures: List[FrameSignature] = []
    for index, (timestamp, phash64, quality, frame) in enumerate(zip(actual_timestamps, phashes, qualities, frames)):
        entropy, mean_luma = quality
        valid = is_valid_for_matching(entropy, mean_luma)
        if _compute_frame_std_luma(frame) < (2.0 / 255.0):
            valid = False
        if is_edge_timestamp(timestamp, duration):
            valid = False
        frame_signatures.append(
            FrameSignature(
                path=Path(path),
                video_id=video_id,
                frame_index=index,
                timestamp_seconds=float(timestamp),
                phash64=int(phash64),
                entropy=float(entropy),
                mean_luma=float(mean_luma),
                valid_for_matching=bool(valid),
            )
        )

    return VideoSignature(
        path=Path(path),
        video_id=video_id,
        duration_seconds=float(duration),
        sampled_frame_count=len(frame_signatures),
        valid_frame_count=sum(1 for signature in frame_signatures if signature.valid_for_matching),
        signatures=frame_signatures,
        extraction_backend=(
            decode_result.backend
            or gpu_decode.LAST_DECODE_BACKEND
            or ("gpu_pynvcodec" if use_gpu else "cpu_ffmpeg")
        ),
        sampling_profile=profile,
    )
