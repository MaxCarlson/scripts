"""
Tests for gpu_capabilities.py — all tests run without CUDA via monkeypatching.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from vdedup.gpu_capabilities import GpuCapabilities, detect_gpu_capabilities, validate_gpu_mode


# ──────────────────────────────────────────
# validate_gpu_mode
# ──────────────────────────────────────────


def test_validate_gpu_mode_accepts_valid():
    assert validate_gpu_mode("auto") == "auto"
    assert validate_gpu_mode("on") == "on"
    assert validate_gpu_mode("off") == "off"


def test_validate_gpu_mode_aliases():
    assert validate_gpu_mode("true") == "on"
    assert validate_gpu_mode("yes") == "on"
    assert validate_gpu_mode("1") == "on"
    assert validate_gpu_mode("false") == "off"
    assert validate_gpu_mode("no") == "off"
    assert validate_gpu_mode("0") == "off"


def test_validate_gpu_mode_case_insensitive():
    assert validate_gpu_mode("AUTO") == "auto"
    assert validate_gpu_mode("On") == "on"
    assert validate_gpu_mode("OFF") == "off"


def test_validate_gpu_mode_invalid():
    with pytest.raises(ValueError, match="Invalid --gpu"):
        validate_gpu_mode("banana")
    with pytest.raises(ValueError):
        validate_gpu_mode("cuda")
    with pytest.raises(ValueError):
        validate_gpu_mode("")


# ──────────────────────────────────────────
# detect_gpu_capabilities: off mode
# ──────────────────────────────────────────


def test_off_mode_returns_immediately_without_imports():
    """--gpu off must not attempt to import torch or PyNvVideoCodec."""
    # If this test accidentally imports torch it would fail on GPU-less CI — that's the guard.
    caps = detect_gpu_capabilities("off")
    assert caps.requested_mode == "off"
    assert caps.route_enabled is False
    assert caps.gpu_available is False
    assert caps.reason_unavailable is not None
    assert "disabled" in caps.reason_unavailable.lower() or "off" in caps.reason_unavailable.lower()


# ──────────────────────────────────────────
# detect_gpu_capabilities: torch missing
# ──────────────────────────────────────────


def _torch_import_error(name: str, *args: Any, **kwargs: Any):
    if name == "torch":
        raise ImportError("No module named 'torch'")
    return original_import(name, *args, **kwargs)


original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__


def test_auto_torch_missing_no_exception():
    """auto mode: missing torch → route_enabled=False, no exception."""
    with patch.dict(sys.modules, {"torch": None}):
        caps = detect_gpu_capabilities("auto")
    assert caps.torch_available is False
    assert caps.cuda_available is False
    assert caps.route_enabled is False
    assert caps.reason_unavailable is not None


def test_on_torch_missing_route_disabled():
    """on mode: missing torch → route_enabled=False (caller should raise)."""
    with patch.dict(sys.modules, {"torch": None}):
        caps = detect_gpu_capabilities("on")
    assert caps.route_enabled is False
    assert caps.reason_unavailable is not None


# ──────────────────────────────────────────
# detect_gpu_capabilities: torch present, CUDA unavailable
# ──────────────────────────────────────────


def _make_torch_mock(cuda_available: bool = True, device_name: str = "Test GPU") -> MagicMock:
    torch_mock = MagicMock()
    torch_mock.cuda.is_available.return_value = cuda_available
    torch_mock.cuda.device_count.return_value = 1 if cuda_available else 0
    torch_mock.cuda.get_device_name.return_value = device_name
    torch_mock.cuda.get_device_capability.return_value = (9, 0)
    torch_mock.cuda.mem_get_info.return_value = (16 * 1024**3, 32 * 1024**3)
    return torch_mock


def test_auto_cuda_unavailable():
    """auto mode: torch present but no CUDA → route_enabled=False."""
    torch_mock = _make_torch_mock(cuda_available=False)
    with patch.dict(sys.modules, {"torch": torch_mock, "PyNvVideoCodec": None}):
        caps = detect_gpu_capabilities("auto")
    assert caps.torch_available is True
    assert caps.cuda_available is False
    assert caps.route_enabled is False
    assert caps.reason_unavailable is not None
    assert "CUDA" in caps.reason_unavailable or "cuda" in caps.reason_unavailable.lower()


# ──────────────────────────────────────────
# detect_gpu_capabilities: CUDA present, PyNvVideoCodec missing
# ──────────────────────────────────────────


def test_auto_pynvcodec_missing():
    """auto mode: torch+CUDA present but PyNvVideoCodec absent → route_enabled=False."""
    torch_mock = _make_torch_mock(cuda_available=True)
    with patch.dict(sys.modules, {"torch": torch_mock, "PyNvVideoCodec": None}):
        caps = detect_gpu_capabilities("auto", require_pynvcodec=True)
    assert caps.torch_available is True
    assert caps.cuda_available is True
    assert caps.pynvcodec_available is False
    assert caps.route_enabled is False
    assert caps.reason_unavailable is not None


def test_auto_pynvcodec_not_required():
    """require_pynvcodec=False: route_enabled=True even without PyNvVideoCodec."""
    torch_mock = _make_torch_mock(cuda_available=True)
    with patch.dict(sys.modules, {"torch": torch_mock, "PyNvVideoCodec": None}):
        caps = detect_gpu_capabilities("auto", require_pynvcodec=False)
    assert caps.torch_available is True
    assert caps.cuda_available is True
    assert caps.route_enabled is True
    assert caps.reason_unavailable is None


# ──────────────────────────────────────────
# detect_gpu_capabilities: all available
# ──────────────────────────────────────────


def test_auto_all_available():
    """auto mode: all dependencies present → route_enabled=True with device info."""
    torch_mock = _make_torch_mock(cuda_available=True, device_name="NVIDIA RTX 5090")
    pynvc_mock = MagicMock()
    with patch.dict(sys.modules, {"torch": torch_mock, "PyNvVideoCodec": pynvc_mock}):
        caps = detect_gpu_capabilities("auto")
    assert caps.gpu_available is True
    assert caps.torch_available is True
    assert caps.cuda_available is True
    assert caps.pynvcodec_available is True
    assert caps.route_enabled is True
    assert caps.device_name == "NVIDIA RTX 5090"
    assert caps.compute_capability == (9, 0)
    assert caps.total_vram_bytes == 32 * 1024**3
    assert caps.free_vram_bytes == 16 * 1024**3
    assert caps.reason_unavailable is None


# ──────────────────────────────────────────
# CLI: --gpu parses correctly
# ──────────────────────────────────────────


def test_cli_gpu_arg_auto():
    from video_dedupe import parse_args
    args = parse_args(["scan", "-D", ".", "-g", "auto"])
    assert args.gpu == "auto"


def test_cli_gpu_arg_on():
    from video_dedupe import parse_args
    args = parse_args(["scan", "-D", ".", "--gpu", "on"])
    assert args.gpu == "on"


def test_cli_gpu_arg_off():
    from video_dedupe import parse_args
    args = parse_args(["scan", "-D", ".", "-g", "off"])
    assert args.gpu == "off"


def test_cli_gpu_arg_invalid_exits():
    from video_dedupe import parse_args
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["scan", "-D", ".", "--gpu", "banana"])
    assert exc_info.value.code == 2


def test_cli_gpu_device_id_default():
    from video_dedupe import parse_args
    args = parse_args(["scan", "-D", "."])
    assert args.gpu_device_id == 0


def test_cli_gpu_device_id_custom():
    from video_dedupe import parse_args
    args = parse_args(["scan", "-D", ".", "--gpu-device-id", "1"])
    assert args.gpu_device_id == 1
