from __future__ import annotations

from PIL import Image
import pytest

from vdedup.gpu_fingerprint import (
    PHASH_SPEC,
    compute_frame_quality,
    compute_phash64_batch,
    is_valid_for_matching,
)


def _solid(value: int) -> Image.Image:
    return Image.new("RGB", (16, 16), (value, value, value))


def test_phash_spec_documents_algorithm_details():
    assert "32x32" in PHASH_SPEC
    assert "0.299R+0.587G+0.114B" in PHASH_SPEC
    assert "orthonormal DCT-II" in PHASH_SPEC
    assert "including DC" in PHASH_SPEC
    assert "lower median" in PHASH_SPEC
    assert "row-major" in PHASH_SPEC
    assert "pure-PIL fallback is threshold-compatible" in PHASH_SPEC


def test_phash64_returns_python_ints():
    hashes = compute_phash64_batch([_solid(0), _solid(255)], use_gpu=False)

    assert len(hashes) == 2
    assert all(isinstance(value, int) for value in hashes)
    assert all(0 <= value < 2**64 for value in hashes)


def test_phash64_identical_frames_are_deterministic():
    frame = Image.new("RGB", (16, 16), (20, 100, 200))

    first = compute_phash64_batch([frame], use_gpu=False)
    second = compute_phash64_batch([frame], use_gpu=False)

    assert first == second


def test_phash64_accepts_hwc_and_chw_nested_lists():
    hwc = [[[(x * 4) % 256, (y * 4) % 256, 100] for x in range(32)] for y in range(32)]
    chw = [
        [[pixel[channel] for pixel in row] for row in hwc]
        for channel in range(3)
    ]

    hashes = compute_phash64_batch([hwc, chw], use_gpu=False)

    assert len(hashes) == 2
    assert hashes[0] == hashes[1]


def test_phash64_cpu_and_torch_paths_match_for_32px_frame():
    torch = pytest.importorskip("torch")
    frame = torch.tensor(
        [[[(x * 4) % 256, (y * 4) % 256, 100] for x in range(32)] for y in range(32)],
        dtype=torch.uint8,
    )

    cpu_hash = compute_phash64_batch([frame], use_gpu=False)
    torch_hash = compute_phash64_batch([frame], use_gpu=True)

    assert torch_hash == cpu_hash


@pytest.mark.gpu
def test_phash64_cuda_tensor_returns_ints():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA is not available")
    frame = torch.randint(0, 256, (1, 3, 32, 32), dtype=torch.uint8, device="cuda")[0]

    hashes = compute_phash64_batch([frame], use_gpu=True)

    assert len(hashes) == 1
    assert isinstance(hashes[0], int)
    assert 0 <= hashes[0] < 2**64


def test_quality_lengths_match_input_count():
    qualities = compute_frame_quality([_solid(0), _solid(255)], use_gpu=False)

    assert len(qualities) == 2


def test_low_entropy_black_and_white_frames_invalid():
    black_quality, white_quality = compute_frame_quality([_solid(0), _solid(255)], use_gpu=False)

    assert is_valid_for_matching(*black_quality) is False
    assert is_valid_for_matching(*white_quality) is False


def test_non_blank_pattern_can_be_valid():
    image = Image.new("RGB", (64, 64))
    pixels = []
    for y in range(64):
        for x in range(64):
            pixels.append((x * 4 % 256, y * 4 % 256, (x + y) * 2 % 256))
    image.putdata(pixels)

    quality = compute_frame_quality([image], use_gpu=False)[0]

    assert is_valid_for_matching(*quality) is True
