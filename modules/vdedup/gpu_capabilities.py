"""
vdedup.gpu_capabilities

Lightweight GPU capability detection for the vdedup pipeline.

This module uses lazy imports so that CPU-only installs never need torch or
PyNvVideoCodec. Import it freely; the expensive detection happens only inside
detect_gpu_capabilities().
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(slots=True)
class GpuCapabilities:
    """Structured result of GPU capability detection."""

    requested_mode: str                        # "auto" | "on" | "off"
    gpu_available: bool                        # torch + CUDA + device all present
    route_enabled: bool                        # True when GPU route should be used
    torch_available: bool
    cuda_available: bool
    pynvcodec_available: bool
    device_id: int
    device_name: Optional[str]
    compute_capability: Optional[Tuple[int, int]]
    free_vram_bytes: Optional[int]
    total_vram_bytes: Optional[int]
    reason_unavailable: Optional[str]          # human-readable when route_enabled=False


def validate_gpu_mode(value: str) -> str:
    """
    Normalise and validate a --gpu argument value.
    Raises ValueError for unrecognised values.
    Accepts aliases: true/yes/1 → on, false/no/0 → off.
    """
    normalised = (value or "").lower().strip()
    aliases = {"true": "on", "false": "off", "yes": "on", "no": "off", "1": "on", "0": "off"}
    normalised = aliases.get(normalised, normalised)
    if normalised not in {"auto", "on", "off"}:
        raise ValueError(
            f"Invalid --gpu value: {value!r}. Must be one of: auto, on, off."
        )
    return normalised


def detect_gpu_capabilities(
    requested_mode: str = "auto",
    device_id: int = 0,
    require_pynvcodec: bool = True,
) -> GpuCapabilities:
    """
    Detect whether the GPU route is available and should be used.

    requested_mode:
        "off"  — return immediately with route_enabled=False; no imports attempted.
        "auto" — try to detect everything; return route_enabled=False on any gap, never raise.
        "on"   — try to detect everything; return route_enabled=False on any gap
                 (the caller is responsible for raising if required).

    require_pynvcodec:
        When True (default), route_enabled requires PyNvVideoCodec in addition to torch+CUDA.

    All GPU library imports are lazy (inside this function only).
    """
    if requested_mode == "off":
        return GpuCapabilities(
            requested_mode="off",
            gpu_available=False,
            route_enabled=False,
            torch_available=False,
            cuda_available=False,
            pynvcodec_available=False,
            device_id=device_id,
            device_name=None,
            compute_capability=None,
            free_vram_bytes=None,
            total_vram_bytes=None,
            reason_unavailable="GPU disabled by user (--gpu off)",
        )

    # ── torch detection ─────────────────────────────────────────────────────
    torch_available = False
    cuda_available = False
    device_name: Optional[str] = None
    compute_capability: Optional[Tuple[int, int]] = None
    free_vram_bytes: Optional[int] = None
    total_vram_bytes: Optional[int] = None

    try:
        import torch  # noqa: PLC0415

        torch_available = True
        cuda_available = bool(torch.cuda.is_available())

        if cuda_available:
            safe_id = min(device_id, torch.cuda.device_count() - 1)
            try:
                device_name = torch.cuda.get_device_name(safe_id)
            except Exception:
                device_name = None
            try:
                compute_capability = torch.cuda.get_device_capability(safe_id)
            except Exception:
                compute_capability = None
            try:
                free_b, total_b = torch.cuda.mem_get_info(safe_id)
                free_vram_bytes = int(free_b)
                total_vram_bytes = int(total_b)
            except Exception:
                pass
    except ImportError:
        torch_available = False
    except Exception:
        torch_available = False

    # ── PyNvVideoCodec detection ─────────────────────────────────────────────
    pynvcodec_available = False
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import PyNvVideoCodec  # noqa: F401, PLC0415

        pynvcodec_available = True
    except ImportError:
        pass
    except Exception:
        pass

    # ── Routing decision ─────────────────────────────────────────────────────
    gpu_available = torch_available and cuda_available

    if not torch_available:
        reason: Optional[str] = "torch is not installed (pip install torch)"
    elif not cuda_available:
        reason = "CUDA is not available (check GPU drivers and CUDA toolkit)"
    elif require_pynvcodec and not pynvcodec_available:
        reason = "PyNvVideoCodec is not installed (pip install PyNvVideoCodec)"
    else:
        reason = None

    route_enabled = gpu_available and (pynvcodec_available or not require_pynvcodec) and reason is None

    return GpuCapabilities(
        requested_mode=requested_mode,
        gpu_available=gpu_available,
        route_enabled=route_enabled,
        torch_available=torch_available,
        cuda_available=cuda_available,
        pynvcodec_available=pynvcodec_available,
        device_id=device_id,
        device_name=device_name,
        compute_capability=compute_capability,
        free_vram_bytes=free_vram_bytes,
        total_vram_bytes=total_vram_bytes,
        reason_unavailable=reason,
    )
