"""
Model inventory discovery, loaded model detection, and safe model transitions for LM Studio.

Provides safe inspection and authorized sequential model switching without blind retries.
All operations support dependency-injected command runners for hermetic offline testing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Optional

import httpx

from .telemetry import collect_resource_snapshot

logger = logging.getLogger(__name__)

CommandRunner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]
DEFAULT_BENCHMARK_CONTEXT_LENGTH = 16384
GIB = 1024**3
GPU_MEMORY_RESERVE_BYTES = 2 * GIB
TOTAL_MEMORY_RESERVE_BYTES = 4 * GIB


class ModelDiscoveryError(RuntimeError):
    """Raised when model inventory discovery fails."""


class ModelTransitionError(RuntimeError):
    """Raised when an authorized model transition fails or times out."""


class ModelTransitionNotAuthorizedError(RuntimeError):
    """Raised when a model transition is required but not explicitly authorized."""


def _parse_memory_value(value: str, unit: str) -> int:
    amount = float(value)
    multiplier = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3,
                  "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3}.get(unit.upper())
    if multiplier is None:
        raise ValueError(f"Unsupported LM Studio memory unit: {unit}")
    return int(amount * multiplier)


def parse_lms_memory_estimate(output: str) -> tuple[int, int]:
    """Return (GPU bytes, total bytes) from `lms load --estimate-only` output."""
    pattern = re.compile(
        r"Estimated\s+(GPU|Total)\s+Memory\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*"
        r"(B|KB|MB|GB|KiB|MiB|GiB)\b",
        re.IGNORECASE,
    )
    estimates: dict[str, int] = {}
    for line in output.splitlines():
        match = pattern.search(line)
        if match:
            estimates[match.group(1).lower()] = _parse_memory_value(match.group(2), match.group(3))
    if "gpu" not in estimates or "total" not in estimates:
        raise ModelTransitionError(
            "Could not parse both GPU and total memory estimates from `lms load --estimate-only`; "
            "no model load was attempted. Check the installed LM Studio CLI output format."
        )
    return estimates["gpu"], estimates["total"]


def _verify_memory_estimate(gpu_bytes: int, total_bytes: int, snapshot) -> None:
    """Fail closed unless estimated allocations fit measured headroom with reserves."""
    if snapshot.gpu_memory_used_bytes is None or snapshot.gpu_memory_total_bytes is None:
        raise ModelTransitionError("Cannot verify free GPU memory for the LM Studio estimate; refusing model load.")
    gpu_available = snapshot.gpu_memory_total_bytes - snapshot.gpu_memory_used_bytes
    if gpu_bytes > max(0, gpu_available - GPU_MEMORY_RESERVE_BYTES):
        raise ModelTransitionError(
            f"LM Studio estimates {gpu_bytes / GIB:.1f} GiB GPU memory, but only "
            f"{gpu_available / GIB:.1f} GiB is free (including a {GPU_MEMORY_RESERVE_BYTES / GIB:.0f} GiB reserve)."
        )
    if snapshot.ram_available_bytes is None:
        raise ModelTransitionError("Cannot verify available host RAM for the LM Studio estimate; refusing model load.")
    total_available = snapshot.ram_available_bytes + gpu_available
    if total_bytes > max(0, total_available - TOTAL_MEMORY_RESERVE_BYTES):
        raise ModelTransitionError(
            f"LM Studio estimates {total_bytes / GIB:.1f} GiB total memory, but measured combined headroom is "
            f"{total_available / GIB:.1f} GiB (including a {TOTAL_MEMORY_RESERVE_BYTES / GIB:.0f} GiB reserve)."
        )


@dataclass(frozen=True, slots=True)
class DownloadedModelInfo:
    """Metadata describing a model available on local disk."""

    model_key: str
    display_name: str
    architecture: str
    size_bytes: int
    quantization: str
    max_context_length: int
    format: str
    path: str
    trained_for_tool_use: bool = False
    model_type: str = "llm"
    selected_variant: str | None = None
    variants: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "display_name": self.display_name,
            "architecture": self.architecture,
            "size_bytes": self.size_bytes,
            "quantization": self.quantization,
            "max_context_length": self.max_context_length,
            "format": self.format,
            "path": self.path,
            "trained_for_tool_use": self.trained_for_tool_use,
            "model_type": self.model_type,
            "selected_variant": self.selected_variant,
            "variants": list(self.variants),
        }

    @classmethod
    def from_lms_dict(cls, data: dict[str, Any]) -> DownloadedModelInfo:
        quant_info = data.get("quantization")
        quant_str = quant_info.get("name", "unknown") if isinstance(quant_info, dict) else str(quant_info or "unknown")
        return cls(
            model_key=data.get("modelKey", data.get("id", "")),
            display_name=data.get("displayName", data.get("modelKey", "")),
            architecture=str(data.get("architecture", "")),
            size_bytes=int(data.get("sizeBytes", 0) or 0),
            quantization=quant_str,
            max_context_length=int(data.get("maxContextLength", 0) or 0),
            format=str(data.get("format", "gguf")),
            path=str(data.get("path", "")),
            trained_for_tool_use=bool(data.get("trainedForToolUse", False)),
            model_type=str(data.get("type", "llm")),
            selected_variant=data.get("selectedVariant") if isinstance(data.get("selectedVariant"), str) else None,
            variants=tuple(value for value in data.get("variants", []) if isinstance(value, str))
            if isinstance(data.get("variants", []), list)
            else (),
        )


@dataclass(frozen=True, slots=True)
class LoadedModelInfo:
    """Metadata describing a model currently loaded into GPU/system memory."""

    identifier: str
    model_key: str
    display_name: str
    status: str
    context_length: int
    size_bytes: int
    max_context_length: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "model_key": self.model_key,
            "display_name": self.display_name,
            "status": self.status,
            "context_length": self.context_length,
            "size_bytes": self.size_bytes,
            "max_context_length": self.max_context_length,
        }

    @classmethod
    def from_lms_dict(cls, data: dict[str, Any]) -> LoadedModelInfo:
        return cls(
            identifier=data.get("identifier", data.get("modelKey", "")),
            model_key=data.get("modelKey", data.get("identifier", "")),
            display_name=data.get("displayName", data.get("identifier", "")),
            status=data.get("status", "unknown"),
            context_length=int(data.get("contextLength", 0) or 0),
            size_bytes=int(data.get("sizeBytes", 0) or 0),
            max_context_length=int(data.get("maxContextLength", 0) or 0),
        )


async def _default_cmd_runner(cmd: list[str]) -> tuple[int, str, str]:
    """Run the local CLI in a worker thread for reliable Windows process creation."""
    operation = cmd[1].lower() if len(cmd) > 1 else ""
    timeout = {"ls": 20.0, "ps": 15.0, "unload": 45.0, "load": 180.0}.get(operation, 20.0)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return -1, stdout, f"{stderr}\nLM Studio command timed out after {timeout:.0f}s".strip()
    return result.returncode, result.stdout or "", result.stderr or ""


async def list_downloaded_models(
    *,
    lms_path: str = "lms",
    runner: Optional[CommandRunner] = None,
    http_base_url: str = "http://127.0.0.1:1234",
) -> list[DownloadedModelInfo]:
    """
    Discover all downloaded local models.

    Prefers `lms ls --json` for rich metadata (quantization, context length, architecture).
    Gracefully falls back to LM Studio's `/v1/models` HTTP endpoint if `lms` is not installed.
    """
    cmd_exec = runner or _default_cmd_runner

    # Try lms CLI first if available or custom runner provided
    if runner is not None or shutil.which(lms_path) is not None:
        try:
            code, stdout, stderr = await cmd_exec([lms_path, "ls", "--json"])
            if code == 0 and stdout.strip():
                data = json.loads(stdout)
                if isinstance(data, list):
                    return [DownloadedModelInfo.from_lms_dict(item) for item in data if isinstance(item, dict)]
        except Exception as exc:
            logger.debug(f"lms ls command failed, falling back to HTTP: {exc}")

    # Fallback to HTTP endpoint
    try:
        async with httpx.AsyncClient(base_url=http_base_url, timeout=5.0) as client:
            resp = await client.get("/v1/models")
            if resp.status_code == 200:
                payload = resp.json()
                items = payload.get("data", [])
                models: list[DownloadedModelInfo] = []
                for it in items:
                    mid = it.get("id", "")
                    if mid:
                        models.append(
                            DownloadedModelInfo(
                                model_key=mid,
                                display_name=mid,
                                architecture="unknown",
                                size_bytes=0,
                                quantization="unknown",
                                max_context_length=0,
                                format="unknown",
                                path="",
                            )
                        )
                return models
    except Exception as exc:
        raise ModelDiscoveryError(
            f"Failed to discover downloaded models via lms CLI or HTTP endpoint: {exc}"
        ) from exc

    return []


async def get_loaded_models(
    *,
    lms_path: str = "lms",
    runner: Optional[CommandRunner] = None,
) -> list[LoadedModelInfo]:
    """
    Query currently loaded models in memory via `lms ps --json`.
    """
    cmd_exec = runner or _default_cmd_runner

    if runner is None and shutil.which(lms_path) is None:
        raise ModelDiscoveryError(f"CLI executable '{lms_path}' not found in PATH.")

    try:
        code, stdout, stderr = await cmd_exec([lms_path, "ps", "--json"])
        if code != 0:
            raise ModelDiscoveryError(f"lms ps failed (exit {code}): {stderr or stdout}")
        data = json.loads(stdout)
        if not isinstance(data, list):
            return []
        return [LoadedModelInfo.from_lms_dict(item) for item in data if isinstance(item, dict)]
    except json.JSONDecodeError as exc:
        raise ModelDiscoveryError(f"Malformed JSON from lms ps: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, ModelDiscoveryError):
            raise
        raise ModelDiscoveryError(f"Error querying loaded models: {exc}") from exc


async def get_loaded_model(
    *,
    lms_path: str = "lms",
    runner: Optional[CommandRunner] = None,
) -> Optional[LoadedModelInfo]:
    """
    Return the primary loaded model in memory, or None if no model is loaded.
    """
    loaded = await get_loaded_models(lms_path=lms_path, runner=runner)
    return loaded[0] if loaded else None


async def transition_model(
    target_model_key: str,
    *,
    allow_transitions: bool = False,
    lms_path: str = "lms",
    unload_timeout: float = 30.0,
    load_timeout: float = 120.0,
    poll_interval: float = 0.25,
    max_ram_pct: float = 90.0,
    expected_model_size_bytes: int | None = None,
    context_length: int = DEFAULT_BENCHMARK_CONTEXT_LENGTH,
    runner: Optional[CommandRunner] = None,
) -> LoadedModelInfo:
    """
    Safely transition the active GPU model in LM Studio.

    Safety Guarantees:
    1. If target is already loaded, returns immediately (no unload).
    2. If target is not loaded and allow_transitions=False, raises ModelTransitionNotAuthorizedError.
    3. If allow_transitions=True:
       - Unloads existing models via `lms unload -a`.
       - Polls until LM Studio reports no loaded models within unload_timeout.
       - Refuses to load when measured host RAM headroom is below the requested model's
         downloaded size plus 25% overhead, or RAM utilization reaches max_ram_pct.
       - Estimates memory and loads via `lms load <key> --context-length <n> -y`.
       - Verifies target model is active, idle, and at the requested context.
       - Halts immediately on any command or service failure without blind retries.
    """
    cmd_exec = runner or _default_cmd_runner

    if not target_model_key or not target_model_key.strip():
        raise ValueError("target_model_key must be a non-empty string")
    if not 0 < max_ram_pct <= 100:
        raise ValueError("max_ram_pct must be greater than 0 and at most 100")
    if isinstance(context_length, bool) or context_length <= 0:
        raise ValueError("context_length must be a positive integer")
    if expected_model_size_bytes is not None and expected_model_size_bytes < 0:
        raise ValueError("expected_model_size_bytes must not be negative")

    required_headroom = (
        int(expected_model_size_bytes * 1.25)
        if expected_model_size_bytes is not None and expected_model_size_bytes > 0
        else None
    )

    loaded_list = await get_loaded_models(lms_path=lms_path, runner=runner)
    target_loaded = next(
        (m for m in loaded_list if m.model_key == target_model_key or m.identifier == target_model_key),
        None,
    )
    if target_loaded and target_loaded.max_context_length and context_length > target_loaded.max_context_length:
        raise ModelTransitionError(
            f"Requested context {context_length} exceeds LM Studio's reported maximum "
            f"{target_loaded.max_context_length} for '{target_model_key}'."
        )
    context_matches = target_loaded is not None and target_loaded.context_length == context_length
    if target_loaded is not None and len(loaded_list) == 1:
        if str(target_loaded.status or "").strip().lower() not in {"idle", "loaded", "ready"}:
            raise ModelTransitionError(
                f"Refusing to dispatch model '{target_model_key}' while LM Studio reports status "
                f"'{target_loaded.status}'. Wait for it to become idle and retry."
            )
        if context_matches:
            snapshot = collect_resource_snapshot()
            if snapshot.ram_pct is not None and snapshot.ram_pct >= max_ram_pct:
                raise ModelTransitionError(
                    f"Refusing to dispatch preloaded model '{target_model_key}': host RAM utilization is "
                    f"{snapshot.ram_pct:.1f}% (safety limit {max_ram_pct:.0f}%)."
                )
            if (snapshot.gpu_memory_used_bytes is not None and snapshot.gpu_memory_total_bytes is not None
                    and snapshot.gpu_memory_total_bytes - snapshot.gpu_memory_used_bytes < GPU_MEMORY_RESERVE_BYTES):
                raise ModelTransitionError(
                    f"Refusing to dispatch preloaded model '{target_model_key}': less than "
                    f"{GPU_MEMORY_RESERVE_BYTES / GIB:.0f} GiB GPU memory remains free."
                )
            logger.info("Model already loaded at requested context; no transition needed target=%s context=%s",
                        target_model_key, context_length, extra={"event_type": "MODEL_READY"})
            return target_loaded

    # Model is not loaded. Check authorization.
    if not allow_transitions:
        current_id = loaded_list[0].identifier if loaded_list else "none"
        if target_loaded is not None and len(loaded_list) == 1:
            raise ModelTransitionNotAuthorizedError(
                f"Model '{target_model_key}' is loaded with context {target_loaded.context_length}, but this "
                f"experiment requests {context_length}. Authorize a model transition to reload it at the "
                "requested context, or choose the loaded context explicitly."
            )
        raise ModelTransitionNotAuthorizedError(
            f"Target model '{target_model_key}' is not the sole loaded model (current loaded: '{current_id}', "
            f"loaded count: {len(loaded_list)}). "
            "Model transitions are not authorized. Set allow_transitions=True or pass --allow-model-transitions."
        )

    # Authorized transition: unload current if any
    if loaded_list:
        active_or_unknown = [
            model for model in loaded_list
            if str(model.status or "").strip().lower() not in {"idle", "loaded", "ready"}
        ]
        if active_or_unknown:
            details = ", ".join(f"{model.model_key} ({model.status})" for model in active_or_unknown)
            logger.error(
                "Model transition refused because LM Studio reports active or unknown model state: %s",
                details,
                extra={"event_type": "MODEL_UNLOAD_BLOCKED"},
            )
            raise ModelTransitionError(
                "Refusing to unload LM Studio model(s) with active or unknown status: "
                f"{details}. Wait for them to become idle and retry."
            )
        logger.info("Unloading LM Studio model set target=%s loaded=%s", target_model_key,
                    [model.model_key for model in loaded_list], extra={"event_type": "MODEL_UNLOAD_START"})
        code, stdout, stderr = await cmd_exec([lms_path, "unload", "-a"])
        logger.info("LM Studio unload finished target=%s exit_code=%s stdout=%s stderr=%s",
                    target_model_key, code, stdout[-1000:], stderr[-1000:],
                    extra={"event_type": "MODEL_UNLOAD_RESULT"})
        if code != 0:
            raise ModelTransitionError(
                f"Failed to unload active model(s) (exit code {code}): {stderr or stdout}"
            )

        # Wait for VRAM/process stabilization
        start_unload = asyncio.get_running_loop().time()
        while True:
            remaining = await get_loaded_models(lms_path=lms_path, runner=runner)
            if not remaining:
                snapshot = collect_resource_snapshot()
                ram_ready = snapshot.ram_pct is not None and snapshot.ram_pct < max_ram_pct
                headroom_ready = (required_headroom is None or (
                    snapshot.ram_available_bytes is not None
                    and snapshot.ram_available_bytes >= required_headroom
                ))
                gpu_ready = (snapshot.gpu_memory_used_bytes is None or snapshot.gpu_memory_total_bytes is None
                             or snapshot.gpu_memory_total_bytes - snapshot.gpu_memory_used_bytes
                             >= GPU_MEMORY_RESERVE_BYTES)
                memory_ready = ram_ready and headroom_ready and gpu_ready
                logger.info(
                    "Post-unload resource check target=%s loaded_models=0 ram_pct=%s ram_available_bytes=%s "
                    "gpu_memory_used_bytes=%s gpu_memory_total_bytes=%s",
                    target_model_key, snapshot.ram_pct, snapshot.ram_available_bytes,
                    snapshot.gpu_memory_used_bytes, snapshot.gpu_memory_total_bytes,
                    extra={"event_type": "MODEL_UNLOAD_VERIFIED" if memory_ready else "MODEL_MEMORY_RELEASE_WAIT"},
                )
                if memory_ready:
                    break
            if asyncio.get_running_loop().time() - start_unload > unload_timeout:
                raise ModelTransitionError(
                    f"Timed out waiting for loaded-model inventory and measured RAM/VRAM headroom "
                    f"after unload ({unload_timeout}s). No next model load was attempted."
                )
            await asyncio.sleep(poll_interval)

    snapshot = collect_resource_snapshot()
    insufficient_headroom = (
        required_headroom is not None
        and snapshot.ram_available_bytes is not None
        and snapshot.ram_available_bytes < required_headroom
    )
    unknown_headroom = required_headroom is not None and snapshot.ram_available_bytes is None
    at_ram_limit = snapshot.ram_pct is not None and snapshot.ram_pct >= max_ram_pct
    if insufficient_headroom or unknown_headroom or at_ram_limit:
        logger.error(
            "Model load blocked by RAM safety guard target=%s ram_pct=%s available_bytes=%s "
            "expected_model_bytes=%s required_headroom_bytes=%s limit_pct=%.1f",
            target_model_key, snapshot.ram_pct, snapshot.ram_available_bytes, expected_model_size_bytes,
            required_headroom, max_ram_pct,
            extra={"event_type": "MODEL_LOAD_BLOCKED"},
        )
        if insufficient_headroom:
            reason = (
                f"available RAM is {snapshot.ram_available_bytes} bytes; "
                f"at least {required_headroom} bytes is required for the model and 25% load headroom"
            )
        elif unknown_headroom:
            reason = "available RAM could not be measured for the expected model size"
        else:
            reason = (
                f"host RAM utilization is {snapshot.ram_pct:.1f}% with "
                f"{snapshot.ram_available_bytes} bytes available (safety limit {max_ram_pct:.0f}%)"
            )
        raise ModelTransitionError(
            f"Refusing to load model '{target_model_key}': {reason}."
        )

    estimate_cmd = [lms_path, "load", target_model_key, "--estimate-only", "--context-length", str(context_length)]
    estimate_code, estimate_stdout, estimate_stderr = await cmd_exec(estimate_cmd)
    logger.info(
        "LM Studio memory estimate target=%s context=%s exit_code=%s stdout=%s stderr=%s",
        target_model_key, context_length, estimate_code, estimate_stdout[-1000:], estimate_stderr[-1000:],
        extra={"event_type": "MODEL_LOAD_ESTIMATE"},
    )
    if estimate_code != 0:
        raise ModelTransitionError(
            f"LM Studio memory estimate failed for '{target_model_key}' (exit code {estimate_code}): "
            f"{estimate_stderr or estimate_stdout}. No model load was attempted."
        )
    # LMS uses stderr for successful human-readable output on some installations.
    # Keep the exit-code check above: diagnostic text from a failed estimate is not approval to load.
    estimated_gpu_bytes, estimated_total_bytes = parse_lms_memory_estimate(
        estimate_stdout + "\n" + estimate_stderr
    )
    _verify_memory_estimate(estimated_gpu_bytes, estimated_total_bytes, snapshot)

    # Load target model
    logger.info(
        "Loading LM Studio model target=%s ram_pct=%s ram_available_bytes=%s",
        target_model_key, snapshot.ram_pct, snapshot.ram_available_bytes,
        extra={"event_type": "MODEL_LOAD_START"},
    )
    code, stdout, stderr = await cmd_exec(
        [lms_path, "load", target_model_key, "--context-length", str(context_length), "-y"]
    )
    logger.info("LM Studio load finished target=%s exit_code=%s stdout=%s stderr=%s",
                target_model_key, code, stdout[-1000:], stderr[-1000:],
                extra={"event_type": "MODEL_LOAD_RESULT"})
    if code != 0:
        raise ModelTransitionError(
            f"Failed to load model '{target_model_key}' (exit code {code}): {stderr or stdout}"
        )

    # Wait for target model to be ready
    start_load = asyncio.get_running_loop().time()
    while True:
        current_loaded = await get_loaded_models(lms_path=lms_path, runner=runner)
        for m in current_loaded:
            if m.model_key == target_model_key or m.identifier == target_model_key:
                if m.context_length != context_length:
                    raise ModelTransitionError(
                        f"LM Studio loaded '{target_model_key}' at context {m.context_length}, "
                        f"but {context_length} was requested; refusing worker dispatch."
                    )
                if str(m.status or "").strip().lower() not in {"idle", "loaded", "ready"}:
                    raise ModelTransitionError(
                        f"LM Studio model '{target_model_key}' loaded but status is '{m.status}', not idle."
                    )
                return m
        if asyncio.get_running_loop().time() - start_load > load_timeout:
            raise ModelTransitionError(
                f"Timed out waiting for model '{target_model_key}' to become ready ({load_timeout}s)."
            )
        await asyncio.sleep(poll_interval)


@dataclass(frozen=True, slots=True)
class AvailableModelInfo:
    """Unified model metadata across local LM Studio, Gemini (via agy), and Codex CLIs."""

    provider: str
    model_key: str
    canonical_id: str
    display_name: str
    status: str
    description: str = ""
    architecture: str = ""
    quantization: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_key": self.model_key,
            "canonical_id": self.canonical_id,
            "display_name": self.display_name,
            "status": self.status,
            "description": self.description,
            "architecture": self.architecture,
            "quantization": self.quantization,
        }


DEFAULT_GEMINI_MODELS: tuple[tuple[str, str], ...] = (
    ("gemini-4-argon-medium", "Gemini 4 Argon (Medium)"),
    ("gemini-4-argon-high", "Gemini 4 Argon (High)"),
    ("gemini-4-argon-low", "Gemini 4 Argon (Low)"),
    ("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)"),
    ("gemini-3.8-flash-medium", "Gemini 3.8 Flash (Medium)"),
    ("gemini-3.8-flash-low", "Gemini 3.8 Flash (Low)"),
)

DEFAULT_CODEX_MODELS: tuple[tuple[str, str, str], ...] = (
    ("gpt-6.1-sol", "GPT-6.1-Sol", "Latest workhorse model for coding and everyday work."),
    ("gpt-6-astra", "GPT-6-Astra", "Frontier intelligence for the most demanding work."),
    ("gpt-6-sol", "GPT-6-Sol", "Previous generation workhorse model."),
    ("gpt-6-luna", "GPT-6-Luna", "Fast and affordable model for easier tasks."),
    ("gpt-5.6-sol", "GPT-5.6-Sol", "Older generation workhorse model."),
    ("gpt-5.6-terra", "GPT-5.6-Terra", "Older balanced model for straightforward work."),
    ("gpt-5.6-luna", "GPT-5.6-Luna", "Older fast and efficient model."),
)

_GEMINI_ALIASES: dict[str, str] = {
    "gemini": "gemini-4-argon-medium",
    "gemini-4-argon": "gemini-4-argon-medium",
    "gemini-4-argon-medium": "gemini-4-argon-medium",
    "gemini-4-argon-high": "gemini-4-argon-high",
    "gemini-4-argon-low": "gemini-4-argon-low",
    "gemini-3.8-flash": "gemini-3.8-flash-high",
    "gemini-3.8-flash-high": "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium": "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low": "gemini-3.8-flash-low",
    "gemini-flash": "gemini-3.8-flash-high",
}

_CODEX_ALIASES: dict[str, str] = {
    "codex": "gpt-6.1-sol",
    "6.1-sol": "gpt-6.1-sol",
    "chatgpt-6.1-sol": "gpt-6.1-sol",
    "gpt-6.1-sol": "gpt-6.1-sol",
    "6-sol": "gpt-6-sol",
    "chatgpt-6-sol": "gpt-6-sol",
    "gpt-6-sol": "gpt-6-sol",
    "6-luna": "gpt-6-luna",
    "chatgpt-6-luna": "gpt-6-luna",
    "gpt-6-luna": "gpt-6-luna",
    "6-astra": "gpt-6-astra",
    "chatgpt-6-astra": "gpt-6-astra",
    "gpt-6-astra": "gpt-6-astra",
    "5.6-sol": "gpt-5.6-sol",
    "chatgpt-5.6-sol": "gpt-5.6-sol",
    "gpt-5.6-sol": "gpt-5.6-sol",
    "5.6-terra": "gpt-5.6-terra",
    "chatgpt-5.6-terra": "gpt-5.6-terra",
    "gpt-5.6-terra": "gpt-5.6-terra",
    "5.6-luna": "gpt-5.6-luna",
    "chatgpt-5.6-luna": "gpt-5.6-luna",
    "gpt-5.6-luna": "gpt-5.6-luna",
}


def resolve_model_provider_and_key(
    raw_model: str,
    default_provider: str = "lmstudio",
) -> tuple[str, str]:
    """
    Resolve a user-supplied model string into (provider, canonical_model_key).

    Supports explicit prefixes (`gemini/...`, `codex/...`, `lms/...`, legacy `lmstudio/...`) and
    friendly shorthand names (`gemini-3.8-flash`, `gemini-4-Argon`, `ChatGpt-6.1-sol`,
    `6-Astra`, `5.6-Terra`, etc.).
    """
    cleaned = raw_model.strip()
    if not cleaned:
        raise ValueError("Model identifier must not be empty")

    explicit_provider: Optional[str] = None
    if "/" in cleaned:
        prefix, rest = cleaned.split("/", 1)
        p_low = prefix.lower()
        if p_low in ("gemini", "agy"):
            explicit_provider = "gemini"
            cleaned = rest.strip()
        elif p_low in ("codex", "chatgpt"):
            explicit_provider = "codex"
            cleaned = rest.strip()
        elif p_low == "openai":
            # Historical Codex aliases used openai/<gpt-model>; LM Studio also
            # serves OpenAI-published local models such as openai/gpt-oss-20b.
            if rest.lower().startswith(("gpt-6", "gpt-5.6")):
                explicit_provider = "codex"
                cleaned = rest.strip()
            else:
                explicit_provider = "lmstudio"
                cleaned = f"openai/{rest.strip()}"
        elif p_low in ("lmstudio", "lms", "local"):
            explicit_provider = "lmstudio"
            cleaned = rest.strip()

    low = cleaned.lower()

    if explicit_provider == "gemini" or (explicit_provider is None and default_provider == "gemini"):
        return "gemini", _GEMINI_ALIASES.get(low, low)

    if explicit_provider == "codex" or (explicit_provider is None and default_provider == "codex"):
        if low in _CODEX_ALIASES:
            return "codex", _CODEX_ALIASES[low]
        norm = low.removeprefix("chatgpt-")
        if not norm.startswith("gpt-") and any(tok in norm for tok in ("sol", "luna", "terra", "astra")):
            norm = f"gpt-{norm}"
        return "codex", norm

    if explicit_provider == "lmstudio":
        return "lmstudio", cleaned

    # Auto-detect from model name when no provider prefix was given
    if low in _GEMINI_ALIASES or low.startswith("gemini") or "argon" in low:
        return "gemini", _GEMINI_ALIASES.get(low, low)

    if low in _CODEX_ALIASES or low.startswith(("gpt-", "chatgpt-")) or any(
        low.endswith(sfx) for sfx in ("-sol", "-luna", "-terra", "-astra")
    ):
        if low in _CODEX_ALIASES:
            return "codex", _CODEX_ALIASES[low]
        norm = low.removeprefix("chatgpt-")
        if not norm.startswith("gpt-"):
            norm = f"gpt-{norm}"
        return "codex", norm

    return default_provider, cleaned


async def list_gemini_models(
    *,
    agy_path: str = "agy",
    runner: Optional[CommandRunner] = None,
) -> list[AvailableModelInfo]:
    """
    Programmatically discover Gemini models available through the local `agy` CLI.
    Falls back to the canonical Gemini catalog if `agy` is unavailable.
    """
    cmd_exec = runner or _default_cmd_runner
    exe = agy_path if runner is not None else (shutil.which(agy_path) or agy_path)

    if runner is not None or shutil.which(agy_path) is not None:
        try:
            code, stdout, _ = await cmd_exec([exe, "models"])
            if code == 0 and stdout.strip():
                discovered: list[AvailableModelInfo] = []
                for line in stdout.splitlines():
                    line_s = line.strip()
                    if not line_s or line_s.lower().startswith("fetching"):
                        continue
                    parts = line_s.split("\t", 1)
                    m_key = parts[0].strip()
                    d_name = parts[1].strip() if len(parts) > 1 else m_key
                    if m_key.lower().startswith("gemini") or "argon" in m_key.lower():
                        discovered.append(
                            AvailableModelInfo(
                                provider="gemini",
                                model_key=m_key,
                                canonical_id=f"gemini/{m_key}",
                                display_name=d_name,
                                status="AVAILABLE (agy)",
                                architecture="gemini",
                            )
                        )
                if discovered:
                    return discovered
        except Exception as exc:
            logger.debug(f"agy models command failed, using fallback catalog: {exc}")

    return [
        AvailableModelInfo(
            provider="gemini",
            model_key=m_key,
            canonical_id=f"gemini/{m_key}",
            display_name=d_name,
            status="CATALOG (agy)",
            architecture="gemini",
        )
        for m_key, d_name in DEFAULT_GEMINI_MODELS
    ]


async def list_codex_models(
    *,
    cache_path: Optional[Path] = None,
) -> list[AvailableModelInfo]:
    """
    Programmatically discover Codex models from `~/.codex/models_cache.json`.
    Falls back to the canonical Codex model catalog if the cache file is absent.
    """
    target_cache = cache_path or (Path.home() / ".codex" / "models_cache.json")
    has_cli = shutil.which("codex") is not None
    status_label = "AVAILABLE (codex)" if has_cli else "CATALOG (codex)"

    if target_cache.is_file():
        try:
            raw = json.loads(target_cache.read_text(encoding="utf-8"))
            models_list = raw.get("models", [])
            discovered: list[AvailableModelInfo] = []
            for item in models_list:
                if not isinstance(item, dict):
                    continue
                slug = str(item.get("slug") or "").strip()
                if not slug or slug == "codex-auto-review":
                    continue
                d_name = str(item.get("display_name") or slug).strip()
                desc = str(item.get("description") or "").strip()
                discovered.append(
                    AvailableModelInfo(
                        provider="codex",
                        model_key=slug,
                        canonical_id=f"codex/{slug}",
                        display_name=d_name,
                        status=status_label,
                        description=desc,
                        architecture="gpt",
                    )
                )
            if discovered:
                return discovered
        except Exception as exc:
            logger.debug(f"Failed reading codex models_cache.json, using fallback catalog: {exc}")

    return [
        AvailableModelInfo(
            provider="codex",
            model_key=slug,
            canonical_id=f"codex/{slug}",
            display_name=d_name,
            status=status_label,
            description=desc,
            architecture="gpt",
        )
        for slug, d_name, desc in DEFAULT_CODEX_MODELS
    ]


async def list_all_available_models(
    *,
    provider: str = "all",
    lms_path: str = "lms",
    agy_path: str = "agy",
    codex_cache_path: Optional[Path] = None,
    runner: Optional[CommandRunner] = None,
    http_base_url: str = "http://127.0.0.1:1234",
) -> list[AvailableModelInfo]:
    """Return available models across requested provider(s) ('all', 'lmstudio', 'gemini', 'codex')."""
    results: list[AvailableModelInfo] = []
    prov = provider.lower().strip()

    if prov in ("all", "gemini", "agy"):
        results.extend(await list_gemini_models(agy_path=agy_path, runner=runner))

    if prov in ("all", "codex", "openai", "chatgpt"):
        results.extend(await list_codex_models(cache_path=codex_cache_path))

    if prov in ("all", "lmstudio", "lms", "local"):
        try:
            downloaded = await list_downloaded_models(
                lms_path=lms_path, runner=runner, http_base_url=http_base_url
            )
            try:
                loaded = await get_loaded_models(lms_path=lms_path, runner=runner)
                loaded_keys = {m.model_key for m in loaded} | {m.identifier for m in loaded}
            except Exception:
                loaded_keys = set()
            for m in downloaded:
                st = "LOADED (active)" if m.model_key in loaded_keys else "DOWNLOADED"
                results.append(
                    AvailableModelInfo(
                        provider="lmstudio",
                        model_key=m.model_key,
                    canonical_id=f"lms/{m.model_key}",
                        display_name=m.display_name,
                        status=st,
                        architecture=m.architecture,
                        quantization=m.quantization,
                    )
                )
        except Exception as exc:
            if prov != "all":
                raise
            logger.debug(f"LM Studio model discovery skipped in 'all' mode: {exc}")

    return results

